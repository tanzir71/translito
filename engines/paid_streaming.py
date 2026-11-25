"""Opt-in paid streaming interpreter, behind local speech/language and budget gates."""
from decimal import Decimal
import re
import queue
import threading

import numpy as np

from engines.cost_guard import CostGuard, GateDecision
from engines.provider import AuthenticationError, ProviderBinding
from engines.settings import EngineSettings, credential_signature
from engines.stream_transport import SocketStream
from engines.streaming_protocols import SonioxProtocol, SpeechmaticsProtocol, ElevenLabsProtocol
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
        self.model = {"soniox": "stt-rt-v6", "elevenlabs": "scribe_v3_live", "speechmatics": "melia-1"}[provider]
        self.translator = None
        self._mt_stop, self._mt_queue = threading.Event(), queue.Queue(maxsize=50)
        self.rate = {"soniox": SONIOX_RATE, "elevenlabs": Rate(per_audio_hour=Decimal(".22")),
                     "speechmatics": Rate(per_audio_hour=Decimal(".20"))}[provider]
        self.billing_mode = "audio_sent" if provider == "elevenlabs" else "open_stream"
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
        if model != {"soniox": "stt-rt-v6", "elevenlabs": "scribe_v3_live", "speechmatics": "melia-1"}[self.name]:
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
        if self.name == "soniox":
            self.protocol = SonioxProtocol(other=next((code for code in conversation if code != "en"), conversation[0]),
                target=output_language, two_way=two_way, terms=self.terms, languages=conversation)
        elif self.name == "elevenlabs":
            self.protocol = ElevenLabsProtocol(languages=conversation)
        else:
            self.protocol = SpeechmaticsProtocol(model="melia-1", languages=conversation)
        if self.name != "soniox" and not getattr(self, "recognition_only", False):
            if self.translator is None:
                raise ValueError("A translator is required after streaming recognition")
            self._mt_stop.clear()
            self._mt_thread = threading.Thread(target=self._translate_finals, daemon=True)
            self._mt_thread.start()
        if self.variety:
            self.protocol_context_variety = self.variety
        self.worker = self.worker_factory(self.protocol, self.credentials, self._update,
            lambda message: self.emit("fallback", message), authorize=self.authorized_key)
        self.guard = CostGuard(self.worker, ledger=self.ledger, rate=self.rate,
            monthly_cap=self.preference.monthly_cap, total_monthly_cap=self.settings.monthly_cap,
            billing_mode=self.billing_mode, languages=conversation, inspect_audio=self.inspect_audio or self._inspect,
            fallback_on_budget=self.settings.fallback_on_budget, emit=on_event)

    def _update(self, update, generation):
        if self.name != "soniox":
            return self._recognizer_update(update, generation)
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

    def _recognizer_update(self, update, generation):
        if getattr(self, "recognition_only", False):
            from engines.types import RecognitionEvent
            for piece in update.pieces:
                self.recognition_callback(RecognitionEvent(piece.text, piece.final, piece.language, piece.start_s, piece.end_s))
            return
        state = self.buffers.setdefault(generation, {"source": "", "turn": 0, "words": 0, "language": self.pair[0]})
        for piece in update.pieces:
            if piece.final:
                state["source"] = (state["source"] + " " + piece.text).strip()
            text = state["source"] if piece.final else (state["source"] + " " + piece.text).strip()
            language = piece.language or state["language"]
            state["language"] = language
            boundary = piece.final and (update.endpoint or update.done or bool(re.search(r"[.!?؟。]\s*$", text)))
            identity = f"{generation}-{state['turn']}"
            self.emit("input_transcription", {"text": text, "language": language, "replace": True,
                "finished": boundary, "utterance_id": identity,
                "end_offset": f"{piece.end_s}s" if piece.end_s is not None else None})
            words = len(state["source"].split())
            if piece.final and (boundary or words - state["words"] >= 5):
                self._mt_queue.put_nowait((identity, state["source"], language, boundary))
                state["words"] = words
            if boundary:
                state["source"], state["words"] = "", 0
                state["turn"] += 1
        if (update.endpoint or update.done) and state["source"]:
            identity = f"{generation}-{state['turn']}"
            self.emit("input_transcription", {"text": state["source"], "language": state["language"],
                "replace": True, "finished": True, "utterance_id": identity})
            self._mt_queue.put_nowait((identity, state["source"], state["language"], True))
            state["source"], state["words"] = "", 0
            state["turn"] += 1

    def _translate_finals(self):
        from engines.cancellation import generation_scope
        context = []
        while not self._mt_stop.is_set():
            try:
                item = self._mt_queue.get(timeout=.1)
            except queue.Empty:
                continue
            if item is None:
                return
            identity, text, language, boundary = item
            try:
                if language == self.target:
                    continue
                with generation_scope(self._mt_stop):
                    result = self.translator.translate(text, language, self.target, context=context[-2:],
                        glossary={term: "" for term in self.terms})
                if self._mt_stop.is_set():
                    return
                self.emit("output_transcription", {"text": result.text, "replace": True, "finished": boundary,
                    "provisional": not boundary, "utterance_id": identity})
                if boundary:
                    context.append((text, result.text))
            except Exception:
                self.emit("fallback", "Streaming translation could not complete. Continuing on this PC.")

    def push_audio(self, audio):
        return self.guard.feed(audio) if self.guard else False

    def start_recognition(self, languages, on_event):
        if self.name == "soniox":
            raise ValueError("Use the interpreter interface for native translation")
        self.recognition_only, self.recognition_callback = True, on_event
        self.start(languages, languages[-1], False, lambda *a: None)

    def stop(self, timeout=2):
        self._mt_stop.set()
        if self.guard:
            self.guard.stop()


def build_soniox(preference, credentials):
    return ProviderBinding(PaidStreamingInterpreter(credentials, preference), rate=SONIOX_RATE,
                           monthly_cap=preference.monthly_cap)

def build_elevenlabs(preference, credentials):
    engine = PaidStreamingInterpreter(credentials, preference, provider="elevenlabs")
    return ProviderBinding(engine, rate=engine.rate, monthly_cap=preference.monthly_cap)


def build_speechmatics(preference, credentials):
    engine = PaidStreamingInterpreter(credentials, preference, provider="speechmatics")
    return ProviderBinding(engine, rate=engine.rate, monthly_cap=preference.monthly_cap)
