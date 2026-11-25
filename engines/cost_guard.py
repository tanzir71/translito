"""Local speech/language gating and reserve-before-open streaming accounting."""
from collections import deque
from dataclasses import dataclass
import math
from uuid import uuid4

import numpy as np

from engines.usage import BudgetExceeded, Units


@dataclass(frozen=True)
class GateDecision:
    probability: float
    language: str | None = None
    no_speech_prob: float = 0


class CostGuard:
    def __init__(self, provider, *, ledger, rate, monthly_cap=0, total_monthly_cap=0,
                 billing_mode="open_stream", languages=(), inspect_audio,
                 close_idle_seconds=8, fallback_on_budget="local", emit=lambda *a: None,
                 skip_non_speech=True, skip_other_languages=True, max_session_seconds=120):
        if billing_mode not in {"open_stream", "audio_sent", "per_request_min"}:
            raise ValueError("Unknown streaming billing mode")
        self.provider, self.ledger, self.rate = provider, ledger, rate
        self.monthly_cap, self.total_monthly_cap = monthly_cap, total_monthly_cap
        self.billing_mode, self.languages, self.inspect = billing_mode, set(languages), inspect_audio
        self.close_idle_seconds = min(10, max(.8, float(close_idle_seconds)))
        self.fallback_on_budget, self.emit = fallback_on_budget, emit
        self.skip_non_speech, self.skip_other_languages = skip_non_speech, skip_other_languages
        self.max_session_seconds = max_session_seconds
        self.session_id = uuid4().hex
        self.captured_seconds = self.sent_seconds = self.speech_seconds = 0.0
        self.active = self.paused = False
        self.onset, self.pre_roll = [], deque(maxlen=10)
        self.onset_seconds = self.idle = self.stream_seconds = self.stream_speech = self.extra = 0.0
        self.reservations = []
        self.finalized = False

    def _reserve(self, seconds):
        estimate = getattr(self.provider, "estimate_usage", None)
        units = estimate(seconds) if callable(estimate) else Units(audio_seconds=seconds, requests=0)
        token = self.ledger.reserve(self.provider.name, units, rate=self.rate,
            monthly_cap=self.monthly_cap, total_monthly_cap=self.total_monthly_cap)
        self.reservations.append(token)

    def _send(self, audio, sample_rate):
        seconds = len(audio) / sample_rate
        self._reserve(seconds)  # Before socket creation, handshake or upload.
        if not self.active:
            self.provider.open_stream()
            self.active = True
            self.stream_seconds = self.stream_speech = self.extra = 0.0
        if self.provider.push_audio(audio) is False:
            raise RuntimeError("The streaming provider stopped accepting audio")
        self.sent_seconds += seconds
        self.stream_seconds += seconds

    def feed(self, audio, sample_rate=16000):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or sample_rate <= 0 or not np.isfinite(audio).all():
            raise ValueError("The cost guard requires finite mono audio")
        duration = len(audio) / sample_rate
        self.captured_seconds += duration
        self.pre_roll.append(audio.copy())  # Local only, never sent to keep alive.
        if self.paused or not duration:
            return not self.paused
        decision = self.inspect(audio, sample_rate)
        threshold = .25 if self.active else .5
        speech = ((not self.skip_non_speech or (decision.probability >= threshold and decision.no_speech_prob < .6))
                  and (not self.skip_other_languages or decision.language in self.languages))
        try:
            if speech:
                self.finalized = False
                self.idle = 0
                self.speech_seconds += duration
                if not self.active:
                    self.onset.append(audio.copy())
                    self.onset_seconds += duration
                    if self.onset_seconds < .25:
                        return True
                    self._send(np.concatenate(self.onset), sample_rate)
                    self.stream_speech += self.onset_seconds
                    self.onset, self.onset_seconds = [], 0
                else:
                    self._send(audio, sample_rate)
                    self.stream_speech += duration
                if self.stream_seconds >= self.max_session_seconds:
                    self.close()
            else:
                self.onset, self.onset_seconds = [], 0
                if self.active:
                    self.idle += duration
                    credit = max(0.0, self.stream_speech * .25 - self.extra)
                    padding = min(duration, credit, .3)
                    if self.billing_mode == "open_stream":
                        if padding:
                            self._reserve(padding)
                            self.extra += padding
                        # Close sooner when needed to keep idle billing bounded.
                        if self.idle >= min(self.close_idle_seconds, self.stream_speech * .25):
                            self.close()
                    elif self.billing_mode == "audio_sent":
                        if self.extra == 0 and padding:
                            self._send(audio[:round(padding * sample_rate)], sample_rate)
                            self.extra += padding
                        if self.idle >= .8 and not self.finalized:
                            self.provider.finalize()
                            self.finalized = True
                        if self.idle >= self.close_idle_seconds:
                            self.close()
                    else:
                        self.close()  # Per-request-minimum engines are not kept live.
            return True
        except BudgetExceeded:
            self.paused = True
            self.close()
            self.emit("budget", {"action": self.fallback_on_budget, "message": "Monthly budget reached."})
            return False
        except Exception:
            self.paused = True
            self.close()
            self.emit("fallback", "Cloud streaming is unavailable. Continuing on this PC.")
            return False

    def close(self):
        try:
            if self.active:
                self.provider.close_stream()
        finally:
            self.active = False
            for token in self.reservations:
                self.ledger.settle(token)  # Uncertain invoices retain reservations.
            self.reservations.clear()

    def stop(self):
        self.close()
        self.ledger.record_session(self.session_id, captured_seconds=self.captured_seconds,
            sent_seconds=self.sent_seconds, translated_chars=0)
