"""Opt-in paid streaming interpreter, behind local speech/language and budget gates."""
from decimal import Decimal
import re

import numpy as np

from engines.cost_guard import CostGuard, GateDecision
from engines.provider import AuthenticationError, ProviderBinding
from engines.settings import EngineSettings, credential_signature
from engines.stream_transport import SocketStream
from engines.streaming_protocols import SonioxProtocol
from engines.usage import Rate, UsageLedger

RATE_CHECKED_ON = "2026-11-25"
SONIOX_RATE = Rate(per_audio_hour=Decimal(".06"), per_million_input_tokens=Decimal("4"),
                   per_million_output_tokens=Decimal("4"))


class PaidStreamingInterpreter:
    requires_network = True
    signals_endpoints = True

    def __init__(self, credentials, preference, *, provider="soniox", settings=None, ledger=None,
                 inspect_audio=None, worker_factory=SocketStream, lid=None, terms=(), variety=""):
        self.name, self.credentials, self.preference = provider, credentials, preference
        self.settings, self.ledger = settings or EngineSettings(), ledger or UsageLedger()
        self.inspect_audio, self.worker_factory, self.lid = inspect_audio, worker_factory, lid
        self.terms, self.variety = terms, variety
        self.model = "stt-rt-v6"
        self.rate, self.billing_mode = SONIOX_RATE, "open_stream"
        self.guard = self.worker = None
        self.buffers = {}
        self._vad = None
        self._tail = np.empty(0, np.float32)

    def authorized_key(self):
        import os
        if os.environ.get("OFFLINE_ONLY", "0").strip() == "1" or self.settings.profile == "offline":
            raise AuthenticationError()
        key = self.credentials.get(self.name)
        if (not self.preference.enabled or self.preference.account_kind != "paid" or not key
                or credential_signature(self.name, key, self.preference) != self.preference.tested_signature):
            raise AuthenticationError()
        return key

    def select_model(self, model):
        if model != "stt-rt-v6":
            raise ValueError("Choose a supported streaming model")
        self.model = model

    def _inspect(self, audio, rate):
        from audio_processing import SpeechActivityDetector
        if self._vad is None:
            self._vad = SpeechActivityDetector()
        self._tail = np.concatenate((self._tail, audio))
        probabilities = []
        while len(self._tail) >= 512:
            probabilities.append(self._vad.speech_probability(self._tail[:512], rate))
            self._tail = self._tail[512:]
        probability = max(probabilities, default=0)
        language = None
        if probability >= .25 and self.lid is not None:
            self._lid_audio = np.concatenate((getattr(self, "_lid_audio", np.empty(0, np.float32)), audio))[-16000:]
            if len(self._lid_audio) >= 4000:
                detect = getattr(self.lid, "detect_any", None) or self.lid.detect
                language = detect(self._lid_audio).language
        return GateDecision(probability, language, 1-probability)

    def start(self, conversation, output_language, two_way, on_event):
        self.authorized_key()
        self.emit, self.pair, self.target = on_event, tuple(conversation), output_language
        self.protocol = SonioxProtocol(other=next((code for code in conversation if code != "en"), conversation[0]),
            target=output_language, two_way=two_way, terms=self.terms, languages=conversation)
        if self.variety:
            self.protocol_context_variety = self.variety
        self.worker = self.worker_factory(self.protocol, self.credentials, self._update,
            lambda message: self.emit("fallback", message), authorize=self.authorized_key)
        self.guard = CostGuard(self.worker, ledger=self.ledger, rate=self.rate,
            monthly_cap=self.preference.monthly_cap, total_monthly_cap=self.settings.monthly_cap,
            billing_mode=self.billing_mode, languages=conversation, inspect_audio=self.inspect_audio or self._inspect,
            fallback_on_budget=self.settings.fallback_on_budget, emit=on_event)

    def _update(self, update, generation):
        state = self.buffers.setdefault(generation, {"source": "", "target": "", "language": None, "end": None})
        source_draft, target_draft = [], []
        for piece in update.pieces:
            if piece.translated:
                if piece.final:
                    state["target"] += piece.text
                else:
                    target_draft.append(piece.text)
            else:
                if piece.final:
                    state["source"] += piece.text
                    if piece.end_s is not None:
                        state["end"] = piece.end_s
                else:
                    source_draft.append(piece.text)
                if piece.language:
                    state["language"] = piece.language
        source = state["source"] + "".join(source_draft)
        if source and any(not piece.translated for piece in update.pieces):
            self.emit("input_transcription", {"text": source, "replace": True, "language": state["language"],
                "finished": update.endpoint or update.done,
                "end_offset": f"{state['end']}s" if state["end"] is not None else None})
        target = state["target"] + "".join(target_draft)
        if target:
            finished = update.done or (not target_draft and bool(re.search(r"[.!?؟。]\s*$", target)))
            self.emit("output_transcription", {"text": target, "replace": True, "finished": finished,
                                                "provisional": not finished})
            if finished:
                state["target"] = ""
        if update.endpoint or update.done:
            state["source"] = ""
        if update.done:
            self.emit("turn_complete", None)

    def push_audio(self, audio):
        return self.guard.feed(audio) if self.guard else False

    def stop(self, timeout=2):
        if self.guard:
            self.guard.stop()


def build_soniox(preference, credentials):
    return ProviderBinding(PaidStreamingInterpreter(credentials, preference), rate=SONIOX_RATE,
                           monthly_cap=preference.monthly_cap)
