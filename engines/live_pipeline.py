"""Desktop row and voice policy around a streaming interpreter and Free fallback."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import queue
import re
import math
import threading
import time
from uuid import uuid4

import numpy as np

from audio_processing import resample_audio
from engines.lid import language_tag, LATIN_LANGUAGES
from engines.cancellation import generation_scope
from engines.protect import protect
from engines.router import route_utterance


_TERMINAL = re.compile(r"[.!?؟。][\s\"'”’»)]*$")


def _offset(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?s", value):
        return None
    result = float(value[:-1])
    return result if math.isfinite(result) else None


class LiveConversationPipeline:
    def __init__(self, fallback, interpreter, *, lid=None, clock=time.monotonic, noise_gate=0):
        self.fallback, self.interpreter, self.lid = fallback, interpreter, lid
        self.conversation, self.mode = fallback.conversation, fallback.mode
        self.emit, self.transcripts, self.stop_event = fallback.emit, fallback.transcripts, fallback.stop_event
        self.player, self.voice = fallback.speech_player, fallback.voice
        self.clock, self.noise_gate = clock, noise_gate
        self.events, self.retained, self.pending = queue.Queue(), deque(), []
        self.live, self.started = True, False
        self.input_row = self.output_row = self.audio_row = None
        self.last_output_row = None
        self.latest_input_row, self.orphan_target = None, []
        self.sample_count, self.transport_base, self.confirmed_end = 0, 0, 0
        self.capture_lock = threading.Lock()
        self.played_chunks = set()

    def start(self):
        self.started = True
        target = self.conversation.my_language if self.mode == "listen" else self.conversation.audience_language
        try:
            self.interpreter.start(("en", self.conversation.other_language), target, False,
                                   lambda kind, data=None: self.events.put((kind, data)))
        except Exception:
            self.live = False
            self.emit("hint", "Live Translate is not configured or its tested key changed. Continuing with the Free profile.")

    def push_capture(self, samples, sample_rate):
        if self.stop_event.is_set() or not self.live:
            return
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError("Live capture requires finite mono or multichannel audio")
        audio = resample_audio(audio, sample_rate, 16000)
        if self.noise_gate and audio.size and float(np.sqrt(np.mean(audio ** 2))) < self.noise_gate:
            audio = np.zeros_like(audio)
        with self.capture_lock:
            self.sample_count += len(audio)
        if not self.interpreter.push_audio(audio):
            self.events.put(("fallback", "Live Translate stopped accepting audio. Continuing with the Free profile."))

    def mark_chunk(self, chunk):
        with self.capture_lock:
            return replace(chunk, stream_end_s=self.sample_count / 16000)

    def notify_speech(self, timestamp):
        self.fallback.notify_speech(timestamp)

    def feed(self, chunk):
        self.poll()
        if self.stop_event.is_set():
            return
        if not self.live:
            self.fallback.feed(chunk)
            return
        self.retained.append(chunk)
        # Cheap local pair-LID preserves the original voice without waiting for
        # cloud timestamps or running another full recognizer. It only applies
        # to the explicitly selected original-voice policy.
        if (self.mode == "speak" and self.player and self.lid is not None
                and self.conversation.same_language_speech == "passthrough"):
            decision = self.lid.detect(chunk.samples)
            if not self.stop_event.is_set() and decision.language == self.conversation.audience_language:
                pcm = (np.clip(chunk.samples, -1, 1) * 32767).astype("<i2").tobytes()
                self.player.play_stream(pcm, rate=chunk.sample_rate)
                self.played_chunks.add(id(chunk))
        self._prune()

    def _new_row(self):
        entry = {"id": uuid4().hex, "timestamp": datetime.now().isoformat(), "mode": self.mode,
                 "engine": self.interpreter.name, "asr_engine": self.interpreter.name, "mt_engine": self.interpreter.name,
                 "source_text": "", "arabic_text": "", "translated_text": "", "english_text": "",
                 "source_language": None, "target_language": self.conversation.my_language if self.mode == "listen"
                 else self.conversation.audience_language, "translation_pending": True, "mt_called": False}
        state = {"entry": entry, "updated": self.clock(), "source_done": False, "target_done": False,
                 "spoken": False, "end": None}
        self.pending.append(state)
        self.transcripts.append(entry)
        self.emit("transcript", entry.copy())
        return state

    def _route(self, state):
        entry = state["entry"]
        tag = language_tag(entry["source_text"], self.conversation.other_language,
                           acoustic_language=entry["source_language"])
        entry["language_tag"] = tag
        route = route_utterance(tag, self.mode, self.conversation)
        entry["pass_through"] = not route.translate
        terms = self.fallback.glossary.translations() if self.fallback.glossary else {}
        state["protection"] = protect(entry["source_text"], "llm",
            latin=route.target == "en" and route.source not in LATIN_LANGUAGES,
            other_script=route.protect_other_script, terms=list(terms) if route.protect_glossary else [])
        return route

    def _source(self, data):
        if self.input_row is None:
            self.input_row = self._new_row()
        state, text = self.input_row, data["text"]
        self.latest_input_row = state
        entry = state["entry"]
        state["raw_source"] = state.get("raw_source", "") + text
        entry["source_text"] = (self.fallback.glossary.restore_english(state["raw_source"])[0]
                                if self.fallback.glossary else state["raw_source"])
        entry["arabic_text"] = entry["source_text"]
        entry["source_language"] = (data.get("language") or entry["source_language"] or "").split("-")[0] or None
        state["updated"] = self.clock()
        ended = _offset(data.get("end_offset"))
        if ended is not None:
            state["end"] = self.transport_base + ended
        route = self._route(state)
        if not route.translate:
            self.orphan_target.clear()
        self.emit("source", entry["source_text"])
        self.emit("arabic", entry["source_text"])
        self.emit("transcript_update", entry.copy())
        if route.translate and self.orphan_target:
            waiting, self.orphan_target = self.orphan_target, []
            for fragment in waiting:
                self._target(fragment)
        if data.get("finished") or _TERMINAL.search(entry["source_text"]):
            state["source_done"] = True
            self.input_row = None
            if not route.translate:
                self._commit(state)
            elif state.get("target_ended"):
                self._commit(state)

    def _target(self, data):
        if self.output_row and not self.output_row["entry"]["translation_pending"]:
            following = next((state for state in self.pending if state is not self.output_row and not state["target_done"]
                              and state["entry"]["source_text"] and self._route(state).translate), None)
            if following:
                self.output_row = following
        if self.output_row is None:
            self.output_row = next((state for state in self.pending if not state["target_done"]
                                    and state["entry"]["source_text"] and self._route(state).translate), None)
            if self.output_row is None:
                if self.latest_input_row and not self._route(self.latest_input_row).translate:
                    return
                self.output_row = self.last_output_row
        if self.output_row is None:
            self.orphan_target.append(data)
            return
        state, entry = self.output_row, self.output_row["entry"]
        self.last_output_row = state
        if state.get("use_free_voice"):
            if data.get("finished"):
                state["target_done"] = True
                self.output_row = None
            return
        entry["translated_text"] += data["text"]
        entry["english_text"] = entry["translated_text"]
        entry["mt_called"] = True
        state["updated"] = self.clock()
        self.audio_row = state
        self.emit("target", entry["translated_text"])
        self.emit("english", entry["translated_text"])
        self.emit("transcript_update", entry.copy())
        if data.get("finished") or _TERMINAL.search(entry["translated_text"]):
            state["target_ended"] = True
            self._commit(state)
        if data.get("finished"):
            state["target_done"] = True
            self.output_row = None

    def _commit(self, state, *, cancelled=False, interrupted=False):
        entry = state["entry"]
        entry["translation_pending"] = False
        if cancelled:
            entry["translation_cancelled"] = True
        if interrupted:
            entry["translation_interrupted"] = True
        route = self._route(state)
        if route.translate and state["protection"].spans and not state["source_done"] and not cancelled and not interrupted:
            entry["translation_pending"] = True
            self.emit("transcript_update", entry.copy())
            return
        if route.translate and entry["translated_text"] and not cancelled and not interrupted and not self.stop_event.is_set():
            protection = state["protection"]
            output = entry["translated_text"]
            if protection.spans and not protection.verify(output):
                # Live Translate cannot accept glossary instructions. A line
                # that changes protected terms uses the shared Free translator
                # and local voice instead of playing that line's native audio.
                terms = self.fallback.glossary.translations() if self.fallback.glossary else {}
                terms = {term: "" for term in terms} if route.target == "en" or route.protect_glossary else {}
                try:
                    with generation_scope(self.stop_event):
                        translated = self.fallback.translator.translate(entry["source_text"], route.source, route.target,
                                                                         context=[], glossary=terms)
                    if not protection.verify(translated.text):
                        raise ValueError("Protected terms were not retained")
                    entry.update(translated_text=translated.text, english_text=translated.text, mt_engine=translated.provider)
                    state["use_free_voice"] = True
                    self.emit("hint", "Live preview changed a protected term. Using Free translation and voice for this line.")
                    self.emit("engine", {"mt": translated.provider, "stage": "mt", "fallback": True})
                except Exception:
                    entry.update(translated_text="", english_text="", translation_error="Protected terms could not be verified; source text was kept.")
                    state["use_free_voice"] = True
            state["verified"] = bool(entry["translated_text"])
            if self.mode == "speak" and self.player and not self.stop_event.is_set():
                if state.get("use_free_voice"):
                    state["audio"] = []
                    if not state["spoken"] and entry["translated_text"]:
                        self.player.enqueue(entry["translated_text"], route.target, self.voice)
                        state["spoken"] = True
                else:
                    for packet in state.pop("audio", []):
                        self.player.play_stream(packet["pcm"], rate=packet["rate"])
        if not route.translate:
            entry["translated_text"] = entry["english_text"] = ""
            if route.secondary_target and not state.get("secondary_done") and not cancelled and not interrupted and not self.stop_event.is_set():
                state["secondary_done"] = True
                terms = self.fallback.glossary.translations() if self.fallback.glossary else {}
                if route.secondary_target == "en" or self.conversation.keep_english_terms:
                    terms = {term: "" for term in terms}
                elif route.secondary_target != "ar":
                    terms = {}
                try:
                    with generation_scope(self.stop_event):
                        result = self.fallback.translator.translate(entry["source_text"], route.source, route.secondary_target,
                                                                    context=[], glossary=terms)
                    entry.update(translated_text=result.text, english_text=result.text, secondary_translation=True,
                                 target_language=route.secondary_target, mt_engine=result.provider, mt_called=True)
                    state["secondary_text"] = result.text
                except Exception:
                    entry["translation_error"] = "Secondary translation was unavailable."
            elif state.get("secondary_text"):
                entry["translated_text"] = entry["english_text"] = state["secondary_text"]
        self.emit("transcript_update", entry.copy())
        if (not cancelled and not interrupted and state["end"] is not None
                and (not route.translate or entry["translated_text"])):
            self.confirmed_end = max(self.confirmed_end, state["end"])
            self._prune()
        if (not state["spoken"] and not self.stop_event.is_set() and self.mode == "speak"
                and self.player and not route.translate and route.speech == "voice"):
            self.player.enqueue(entry["source_text"], route.target, self.voice)
            state["spoken"] = True

    def _prune(self):
        while self.retained and self.retained[0].stream_end_s is not None and self.retained[0].stream_end_s <= self.confirmed_end:
            self.played_chunks.discard(id(self.retained.popleft()))

    def _fallback(self, message):
        if not self.live:
            return
        self.live = False
        self.interpreter.stop(timeout=0)
        if self.player:
            self.player.reset_stream()
        self.emit("hint", message)
        self.emit("engine", {"asr": "Free fallback", "mt": "Free fallback", "fallback": True})
        for state in self.pending:
            if state["entry"]["translation_pending"]:
                self._commit(state, interrupted=True)
        if self.retained:
            self.emit("hint", "Recovering retained audio with Free. Some overlapping text may repeat.")
        while self.retained and not self.stop_event.is_set():
            chunk = self.retained.popleft()
            player = self.fallback.speech_player
            if id(chunk) in self.played_chunks:
                self.fallback.speech_player = None
            try:
                self.fallback.feed(chunk)
            finally:
                self.fallback.speech_player = player
        self.played_chunks.clear()

    def _handle(self, kind, data, *, text_only=False):
        text_only = text_only or not self.live
        if kind == "input_transcription":
            self._source(data)
        elif kind == "output_transcription":
            self._target(data)
        elif text_only:
            return
        elif kind == "connected":
            if data and not data.get("resumed"):
                self.transport_base = data.get("offset_s", 0)
                for state in self.pending:
                    if state["entry"]["translation_pending"]:
                        self._commit(state, interrupted=True)
                self.input_row = self.output_row = self.audio_row = None
                self.last_output_row = None
                self.latest_input_row, self.orphan_target = None, []
            self.emit("engine", {"asr": self.interpreter.name, "mt": self.interpreter.name, "fallback": False})
            self.emit("status", "listening")
        elif kind in {"reconnecting", "interrupted"}:
            if self.player:
                self.player.reset_stream()
            self.audio_row = None
            self.emit("status", "Reconnecting…" if kind == "reconnecting" else "listening")
        elif kind == "status":
            self.emit("status", data)
        elif kind == "audio":
            state = self.audio_row or next((state for state in self.pending if not state["target_done"]
                                           and state["entry"]["source_text"] and self._route(state).translate), None)
            if self.mode == "speak" and self.player and state and self._route(state).translate:
                if state.get("use_free_voice"):
                    return
                if state["protection"].spans and not state.get("verified"):
                    state.setdefault("audio", []).append(data)
                else:
                    self.player.play_stream(data["pcm"], rate=data["rate"])
        elif kind == "turn_complete":
            self.audio_row = None
        elif kind == "fallback":
            self._fallback(data)

    def poll(self):
        if self.stop_event.is_set():
            return
        if not self.live:
            self.fallback.poll()
            return
        while not self.events.empty():
            self._handle(*self.events.get_nowait())
        if not self.live:
            for state in self.pending:
                if state["entry"]["translation_pending"]:
                    self._commit(state, interrupted=True)
            self.fallback.poll()
            return
        now = self.clock()
        for state in self.pending:
            if not state["target_done"] and now - state["updated"] >= 1.2:
                if self._route(state).translate and not state["entry"]["translated_text"]:
                    if now - state["updated"] >= 8:
                        self._fallback("Live Translate returned no target text. Continuing with the Free profile.")
                        break
                    continue
                state["source_done"] = state["target_done"] = True
                self._commit(state)
                if self.input_row is state:
                    self.input_row = None
                if self.output_row is state:
                    self.last_output_row = state
                    self.output_row = None
        # Retain source entries in transcripts, not in the controller work list.
        self.pending[:] = [state for state in self.pending if not state["target_done"] or state is self.audio_row]

    def flush(self):
        self.poll()
        if not self.live:
            return self.fallback.flush()
        for state in self.pending:
            self._commit(state)

    def cancel(self):
        self.interpreter.stop(timeout=.2)
        # Keep text already produced before Stop; never play queued audio here.
        while not self.events.empty():
            self._handle(*self.events.get_nowait(), text_only=True)
        for state in self.pending:
            if state["entry"]["translation_pending"]:
                self._commit(state, cancelled=True)
        self.fallback.cancel()
        self.retained.clear()
        self.played_chunks.clear()
        self.pending.clear()
        self.orphan_target.clear()
        self.input_row = self.output_row = self.audio_row = self.last_output_row = self.latest_input_row = None

    def stop(self):
        self.interpreter.stop(timeout=.2)
