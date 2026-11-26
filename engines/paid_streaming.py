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

RATE_CHECKED_ON = "2026-11-26"
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
        self._session_generation = 0
        self._callback_lock = threading.RLock()
        self.rate = {"soniox": SONIOX_RATE, "elevenlabs": Rate(per_audio_hour=Decimal(".22")),
                     "speechmatics": Rate(per_audio_hour=Decimal(".40"))}[provider]
        self.billing_mode = "audio_sent" if provider == "elevenlabs" else "open_stream"
        self.guard = self.worker = None
        self.gates_target_language = True
        self.buffers = {}
        self.commits, self.annotations, self.timings = {}, {}, {}
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
        if probability < .25:
            self._lid_audio = np.empty(0,np.float32)
        language = None
        if probability >= .25 and self.lid is not None:
            self._lid_audio = np.concatenate((getattr(self, "_lid_audio", np.empty(0, np.float32)), audio))[-16000:]
            if len(self._lid_audio) >= 4000:
                detect = getattr(self.lid, "detect_any", None) or self.lid.detect
                language = detect(self._lid_audio).language
        return GateDecision(probability, language, 1-probability)

    def start(self, conversation, output_language, two_way, on_event):
        self.authorized_key()
        with self._callback_lock:
            self._session_generation += 1
            session = self._session_generation
            self._mt_stop.set()
            self._mt_stop, self._mt_queue = threading.Event(), queue.Queue(maxsize=50)
            self.buffers, self.commits, self.annotations, self.timings = {}, {}, {}, {}
            self._tail, self._lid_audio = np.empty(0, np.float32), np.empty(0, np.float32)
            self.emit = lambda kind, data=None: on_event(kind, data) if session == self._session_generation else None
            self.pair, self.target = tuple(conversation), output_language
        if self.name == "soniox":
            self.protocol = SonioxProtocol(other=next((code for code in conversation if code != "en"), conversation[0]),
                target=output_language, two_way=two_way, terms=self.terms, languages=conversation,
                native_translation=getattr(self, "native_translation", True))
        elif self.name == "elevenlabs":
            self.protocol = ElevenLabsProtocol(languages=conversation)
        else:
            self.protocol = SpeechmaticsProtocol(model="melia-1", languages=conversation)
        if (self.name != "soniox" or not getattr(self, "native_translation", True)) and not getattr(self, "recognition_only", False):
            if self.translator is None:
                raise ValueError("A translator is required after streaming recognition")
            self._mt_thread = threading.Thread(target=self._translate_finals,
                args=(self._mt_stop, self._mt_queue, self.emit), daemon=True)
            self._mt_thread.start()
        if self.variety:
            self.protocol.variety = self.variety
        emit = self.emit
        def update(raw, generation):
            with self._callback_lock:
                if session == self._session_generation:
                    self._update(raw, generation)
        self.worker = self.worker_factory(self.protocol, self.credentials,
            update,
            lambda message: emit("fallback", message), authorize=self.authorized_key)
        from app_config import read_config
        config = read_config()
        self.guard = CostGuard(self.worker, ledger=self.ledger, rate=self.rate,
            monthly_cap=self.preference.monthly_cap, total_monthly_cap=self.settings.monthly_cap,
            billing_mode=self.billing_mode, languages=conversation, inspect_audio=self.inspect_audio or self._inspect,
            excluded_languages=(output_language,),
            fallback_on_budget=self.settings.fallback_on_budget, emit=self.emit,
            skip_non_speech=config.getboolean("COSTGUARD", "skip_non_speech", fallback=True),
            skip_other_languages=config.getboolean("COSTGUARD", "skip_other_languages", fallback=True),
            close_idle_seconds=config.getfloat("COSTGUARD", "close_idle_seconds", fallback=8))
        self.guard.budget_warn_percent = self.settings.budget_warn_percent

    def _update(self, update, generation):
        if self.name != "soniox" or not getattr(self, "native_translation", True):
            return self._recognizer_update(update, generation)
        state = self.buffers.setdefault(generation, {"source": "", "target": "", "language": None, "end": None,"languages":set()})
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
                    state["languages"].add(piece.language)
                    state["language"] = "mix" if len(state["languages"]) > 1 else piece.language
        source = state["source"] + "".join(source_draft)
        if source and any(not piece.translated for piece in update.pieces):
            self.emit("input_transcription", {"text": source, "replace": True, "language": state["language"],
                "finished": update.endpoint or update.done,
                "speech_end_at": self.guard.speech_end_at(state["end"], generation) if self.guard and state["end"] is not None else None,
                "end_offset": f"{state['end']}s" if state["end"] is not None else None})
        target = state["target"] + "".join(target_draft)
        if target:
            finished = update.done or (not target_draft and bool(re.search(r"[.!?؟。]\s*$", target)))
            self.emit("output_transcription", {"text": target, "replace": True, "finished": finished,
                                                "provisional": not finished})
            if finished:
                if self.guard:
                    self.guard.translated_chars += len(target)
                    self.ledger.record_session(self.guard.session_id,translated_chars=self.guard.translated_chars)
                state["target"] = ""
        if update.endpoint or update.done:
            state["source"] = ""
            state["languages"].clear()
        if update.done:
            self.emit("turn_complete", None)

    def _recognizer_update(self, update, generation):
        if getattr(self, "recognition_only", False):
            from engines.types import RecognitionEvent
            for piece in update.pieces:
                self.recognition_callback(RecognitionEvent(piece.text, piece.final, piece.language, piece.start_s, piece.end_s))
            return
        state = self.buffers.setdefault(generation, {"source": "", "turn": 0, "words": 0, "language":next((code for code in self.pair if code != self.target),self.pair[0])})
        for piece in update.pieces:
            if piece.final:
                state["source"] = (state["source"] + " " + piece.text).strip()
            text = state["source"] if piece.final else (state["source"] + " " + piece.text).strip()
            language = piece.language or state["language"]
            state["language"] = language
            boundary = piece.final and (update.endpoint or update.done or bool(re.search(r"[.!?؟。]\s*$", text)))
            identity = f"{generation}-{state['turn']}"
            if piece.final:
                self.commits.setdefault(generation, []).append({"text": piece.text.strip(), "id": identity,
                    "end": self.guard.speech_end_at(piece.end_s, generation) if self.guard and piece.end_s is not None else None})
            self.emit("input_transcription", {"text": text, "language": language, "replace": True,
                "finished": boundary, "utterance_id": identity,
                "speech_end_at": self.guard.speech_end_at(piece.end_s, generation) if self.guard and piece.end_s is not None else None,
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
        annotations = self.annotations.setdefault(generation, {})
        for piece in update.annotations:
            key = (piece.text.strip(), piece.start_s, piece.end_s)
            if key in annotations and annotations[key] != piece:
                annotations[key] = None
            elif key not in annotations:
                annotations[key] = piece
        self._join_timing(generation)

    def _join_timing(self, generation):
        """Late vendor metadata updates timing only, never source or MT work."""
        from collections import defaultdict
        commits, metadata, rows = defaultdict(list), defaultdict(list), defaultdict(list)
        for commit in self.commits.get(generation, ()):
            commits[commit["text"]].append(commit)
            rows[commit["id"]].append(commit)
        for piece in self.annotations.get(generation, {}).values():
            if piece is not None and piece.start_s is not None and piece.end_s is not None and piece.start_s <= piece.end_s:
                metadata[piece.text.strip()].append(piece)
        for text, group in commits.items():
            candidates = metadata[text]
            if len(candidates) == len(group):
                for commit, piece in zip(group, sorted(candidates, key=lambda p: (p.start_s,p.end_s))):
                    if self.guard:
                        commit["end"] = self.guard.speech_end_at(piece.end_s, generation)
        for identity, group in rows.items():
            if all(c["end"] is not None for c in group):
                end = max(c["end"] for c in group)
                if self.timings.get(identity) != end:
                    self.timings[identity] = end
                    self.emit("timing", {"utterance_id": identity, "speech_end_at": end})

    def _translate_finals(self, stop=None, jobs=None, emit=None):
        from engines.cancellation import generation_scope
        stop, jobs, emit = stop or self._mt_stop, jobs or self._mt_queue, emit or self.emit
        context = []
        while not stop.is_set():
            try:
                item = jobs.get(timeout=.1)
            except queue.Empty:
                continue
            if item is None:
                return
            identity, text, language, boundary = item
            try:
                if language == self.target:
                    continue
                with generation_scope(stop):
                    result = self.translator.translate(text, language, self.target, context=context[-2:],
                        glossary={term: "" for term in self.terms})
                if stop.is_set():
                    return
                emit("output_transcription", {"text": result.text, "replace": True, "finished": boundary,
                    "provisional": not boundary, "utterance_id": identity})
                if boundary:
                    context.append((text, result.text))
                    if self.guard:
                        self.guard.translated_chars += len(result.text)
                        self.ledger.record_session(self.guard.session_id,translated_chars=self.guard.translated_chars)
            except Exception:
                if not stop.is_set():
                    emit("fallback", "Streaming translation could not complete. Continuing on this PC.")

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
