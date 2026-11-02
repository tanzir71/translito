"""The bilingual event/assembly/translation path shared by live and replay."""
from datetime import datetime
from uuid import uuid4
import time

import numpy as np

from engines.router import route_utterance
from engines.cancellation import generation_scope
from engines.sentence_assembler import SentenceAssembler


class ConversationPipeline:
    def __init__(self, recognizer, translator, conversation, *, mode="listen", emit,
                 transcripts, stop_event, speech_player=None, voice="Automatic", glossary=None,
                 assembler=None):
        self.recognizer = recognizer
        self.translator = translator
        self.conversation = conversation
        self.mode = mode
        self.emit = emit
        self.transcripts = transcripts
        self.stop_event = stop_event
        self.speech_player = speech_player
        self.voice = voice
        self.glossary = glossary
        self.assembler = assembler or SentenceAssembler()
        self.pending_entry = None
        self.context = []
        self.last_empty_hint_at = None
        self.last_speech_at = None

    def notify_speech(self, timestamp):
        self.last_speech_at = timestamp
        if self.assembler.pending:
            self.assembler.updated_at = timestamp

    def feed(self, chunk):
        if chunk.kind != "audio" or self.stop_event.is_set():
            return
        self.emit("status", "transcribing")
        result = self.recognizer.transcribe(chunk.samples, chunk.sample_rate,
                                           hint_language=None, prompt=None, stop_event=self.stop_event)
        if self.stop_event.is_set():
            return
        if not result.text:
            self.emit("status", "listening")
            now = time.monotonic()
            if self.last_empty_hint_at is None or now - self.last_empty_hint_at >= 10:
                self.emit("hint", "No speech was recognized from this segment. Check the source "
                          "and the conversation languages.")
                self.last_empty_hint_at = now
            return
        self.emit("source", result.text)
        self.emit("arabic", result.text)
        route = route_utterance(result.language_tag, self.mode, self.conversation)
        merge = (route.translate and self.pending_entry is not None
                 and self.pending_entry["language_tag"] == result.language_tag)
        if merge:
            entry = self.pending_entry
            entry["source_text"] += " " + result.text
            entry["arabic_text"] = entry["source_text"]
            self.emit("transcript_update", entry.copy())
        else:
            entry = {
                "id": uuid4().hex, "timestamp": datetime.now().isoformat(),
                "source_text": result.text, "translated_text": "", "arabic_text": result.text,
                "english_text": "", "source_language": result.language,
                "language_tag": result.language_tag, "target_language": route.target,
                "translation_pending": route.translate or bool(route.secondary_target),
                "pass_through": not route.translate, "mode": self.mode,
                "asr_engine": result.provider, "avg_logprob": result.avg_logprob,
                "language_probability": result.language_prob,
            }
            self.transcripts.append(entry)
            self.emit("transcript", entry.copy())
        part = (entry, chunk)
        if not route.translate:
            self.flush()
            self._finish(entry, [chunk], route)
            return
        self.pending_entry = entry
        for sentence in self.assembler.push(result.text, result.language_tag, part):
            self._finish_sentence(sentence)
        if self.assembler.pending:
            # The timeout is measured from speech, not from ASR completion.
            # A slow recognizer must not add another 1.5s of artificial silence.
            speech_end = (chunk.captured_at - (chunk.endpoint_delay_s or 0)
                          if chunk.captured_at is not None else None)
            known = [value for value in (speech_end, self.last_speech_at) if value is not None]
            if known:
                self.assembler.updated_at = max(known)
        if not self.assembler.pending:
            self.pending_entry = None

    def _finish_sentence(self, sentence):
        entry = sentence.parts[0][0]
        route = route_utterance(sentence.language_tag, self.mode, self.conversation)
        self._finish(entry, [part[1] for part in sentence.parts], route)

    def _finish(self, entry, chunks, route):
        captured = [chunk.captured_at for chunk in chunks if chunk.captured_at is not None]
        ended = [chunk.captured_at - chunk.endpoint_delay_s for chunk in chunks
                 if chunk.captured_at is not None and chunk.endpoint_delay_s is not None]
        entry.update(captured_at=max(captured) if captured else None,
                     speech_end_at=max(ended) if ended else None, segment_count=len(chunks))
        if self.stop_event.is_set():
            entry.update(translation_pending=False, translation_cancelled=True)
            self.emit("transcript_update", entry.copy())
            return
        try:
            output = entry["source_text"]
            target = route.target
            if route.translate or route.secondary_target:
                target = route.secondary_target or target
                self.emit("status", "translating")
                entry["mt_called"] = True
                glossary = self.glossary.translations() if self.glossary else {}
                if target == "en" or route.protect_glossary or route.protect_latin:
                    glossary = {term: "" for term in glossary}
                elif target != "ar":
                    glossary = {}
                else:
                    glossary = {term: value for term, value in glossary.items() if value}
                with generation_scope(self.stop_event):
                    translated = self.translator.translate(
                        output, route.source, target,
                        context=self.context[-2:] if route.translate else [], glossary=glossary)
                if self.stop_event.is_set():
                    entry.update(translation_pending=False, translation_cancelled=True)
                    self.emit("transcript_update", entry.copy())
                    return
                output = translated.text
                entry.update(translated_text=output, english_text=output, target_language=target,
                             mt_engine=translated.provider, secondary_translation=bool(route.secondary_target))
                self.emit("engine", {"asr": entry["asr_engine"], "mt": translated.provider})
            else:
                entry["mt_called"] = False
            entry["translation_pending"] = False
            self.emit("target", output)
            self.emit("english", output)
            self.emit("transcript_update", entry.copy())
            if route.translate:
                self.context.append((entry["source_text"], output))
            speaking = False
            if self.mode == "speak" and self.speech_player and not self.stop_event.is_set():
                if route.speech == "passthrough":
                    # Capture preprocessing has already made every chunk mono
                    # at the ASR rate; output resampling happens in the player.
                    self.emit("status", "speaking")
                    speaking = True
                    self.speech_player.enqueue_audio(np.concatenate([chunk.samples for chunk in chunks]),
                                                     chunks[0].sample_rate)
                elif route.speech == "voice":
                    self.emit("status", "speaking")
                    speaking = True
                    self.speech_player.enqueue(output, route.target, self.voice)
            if not speaking:
                self.emit("status", "listening")
        except Exception as exc:
            if self.stop_event.is_set():
                entry.update(translation_pending=False, translation_cancelled=True)
                self.emit("transcript_update", entry.copy())
                return
            entry.update(translation_pending=False, translation_error=str(exc))
            self.emit("transcript_update", entry.copy())
            self.emit("error", str(exc))

    def poll(self):
        for sentence in self.assembler.poll():
            self._finish_sentence(sentence)
        if not self.assembler.pending:
            self.pending_entry = None

    def flush(self):
        for sentence in self.assembler.flush():
            self._finish_sentence(sentence)
        self.pending_entry = None

    def cancel(self):
        for sentence in self.assembler.flush():
            entry = sentence.parts[0][0]
            entry.update(translation_pending=False, translation_cancelled=True)
            self.emit("transcript_update", entry.copy())
        self.pending_entry = None
