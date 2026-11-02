"""Evaluation rows and timing metadata; never a production booster adapter."""
from collections import defaultdict
import time
from types import SimpleNamespace

import numpy as np

from engines.lid import language_tag, latin_ratio


class CascadedRows:
    """Use desktop sentence assembly, routing, glossary protection and MT.

    All pipeline operations run on one consumer. Metadata joins happen after
    that consumer drains; they never decode, reroute or translate text again.
    """
    def __init__(self, provider, target, translator, glossary, stop_event, *, assembler=None, clock=time.perf_counter):
        from engines.conversation_pipeline import ConversationPipeline
        from engines.router import Conversation
        from engines.sentence_assembler import SentenceAssembler
        self.provider, self.target, self.glossary = provider, target, glossary
        self.entries, self.errors, self.completed = [], [], {}
        self.mt_calls, self.commits = [], []
        self.annotations = {}
        self.current = None
        self.clock = clock
        self.pipeline = ConversationPipeline(
            SimpleNamespace(transcribe=lambda *a, **kw: self.current),
            SimpleNamespace(translate=self.translate), Conversation(my_language=target),
            mode="listen", emit=self.event, transcripts=self.entries, stop_event=stop_event,
            glossary=glossary, assembler=assembler or SentenceAssembler(clock=clock))
        self.translator = translator

    def translate(self, text, *args, **kwargs):
        self.mt_calls.append(text)
        return self.translator.translate(text, *args, **kwargs)

    def event(self, kind, payload):
        if kind == "error":
            self.errors.append("The evaluation MT pipeline could not complete a row.")
        if kind == "transcript_update" and not payload.get("translation_pending"):
            self.completed.setdefault(payload["id"], self.clock())

    def feed(self, piece, origin):
        from engines.postprocess import postprocess
        from engines.types import AsrResult
        text, hits = self.glossary.restore_english(piece.text)
        text = postprocess(text).text
        if not text or self.pipeline.stop_event.is_set():
            return
        tag = language_tag(text, transliteration_hits=hits, acoustic_language=piece.language)
        self.current = AsrResult(text, piece.language or ("en" if tag == "en" else "ar"), None,
                                 tag, latin_ratio(text), None, None,
                                 max(0, (piece.end_s or 0) - (piece.start_s or 0)), self.provider)
        end = origin + piece.end_s if origin is not None and piece.end_s is not None else None
        chunk = SimpleNamespace(kind="audio", samples=np.empty(0, dtype=np.float32), sample_rate=16000,
                                captured_at=end, endpoint_delay_s=0 if end is not None else None)
        self.pipeline.feed(chunk)
        self.commits.append(SimpleNamespace(text=piece.text, chunk=chunk, entry=self.entries[-1],
                                             start=piece.start_s, end=piece.end_s, language=piece.language))

    def annotate(self, piece, origin):
        # A repeated metadata delivery is not another utterance. If a vendor
        # sends conflicting metadata for the same interval, leave it unjoined.
        key = (piece.text, piece.start_s, piece.end_s)
        previous = self.annotations.get(key)
        if previous and previous[0] != piece:
            self.annotations[key] = (None, origin)
        elif key not in self.annotations:
            self.annotations[key] = (piece, origin)

    def finish_timing(self, audio_seconds):
        commits, annotations = defaultdict(list), defaultdict(list)
        for commit in self.commits:
            commits[commit.text].append(commit)
        for piece, origin in self.annotations.values():
            if piece is not None and piece.start_s is not None and piece.end_s is not None and origin is not None:
                annotations[piece.text].append((piece, origin))
        invalid = False
        for text, group in commits.items():
            candidates = annotations[text]
            # Identical repeated utterances match by commit order and audio
            # interval order, only when the complete group is accounted for.
            # Missing/extra intervals stay unknown rather than guessing a row.
            if len(candidates) == len(group) and all(c.end is None for c in group):
                for commit, (piece, origin) in zip(group, sorted(candidates, key=lambda p: (p[0].start_s, p[0].end_s))):
                    commit.start, commit.end, commit.language = piece.start_s, piece.end_s, piece.language
                    commit.chunk.captured_at, commit.chunk.endpoint_delay_s = origin + piece.end_s, 0
            for commit in group:
                if commit.end is not None and (commit.end > audio_seconds + .001
                        or commit.start is None or commit.start > commit.end):
                    commit.chunk.captured_at = None
                    invalid = True
        if invalid:
            self.errors.append("Vendor timestamps are outside the replay audio or lack a valid word interval.")
        by_entry = defaultdict(list)
        for commit in self.commits:
            by_entry[commit.entry["id"]].append(commit)
        observed, expected = [], len(self.entries)
        for entry in self.entries:
            group = by_entry[entry["id"]]
            completed = self.completed.get(entry["id"])
            complete = bool(group) and all(c.chunk.captured_at is not None for c in group)
            end = max(c.chunk.captured_at for c in group) if complete else None
            # Negative timing would make a provider appear spuriously fast.
            valid = (complete and completed is not None and completed >= end
                     and not entry.get("translation_error") and not entry.get("translation_pending"))
            entry.update(captured_at=end, speech_end_at=end,
                         vendor_languages=sorted({c.language for c in group if c.language in {"en", "ar"}}),
                         speech_end_latency_s=completed - end if valid else None,
                         latency_timing_status="complete" if valid else "unavailable")
            if valid:
                observed.append(entry["speech_end_latency_s"])
        return observed, expected


class SonioxRows:
    """Group source tokens without inventing source/translation alignment.

    Source utterances and drafts preserve endpoints. The native target stream
    stays separate for clip chrF because translated tokens have no timestamps
    or unique source-utterance IDs. That limitation must survive reporting.
    """
    def __init__(self, target="en", idle_seconds=1.2):
        self.target, self.idle_seconds = target, idle_seconds
        self.entries, self.pending, self.partials, self.targets = [], [], [], []
        self.last_text_at, self.origin = None, None

    @property
    def draft_source(self):
        return "".join(p.text for p in (*self.pending, *self.partials))

    @property
    def target_text(self):
        return "".join(self.targets).strip()

    def push(self, update, now, origin):
        if origin is not None:
            self.origin = origin
        boundaries = set(update.boundaries)
        partials = []
        for index, piece in enumerate(update.pieces):
            if index in boundaries:
                self.flush(now, "endpoint")
            if not piece.translated:
                self.last_text_at = now
                if piece.final:
                    self.pending.append(piece)
                else:
                    partials.append(piece)
            if piece.final and ((piece.translated and piece.language == self.target)
                    or (piece.translation_status == "none" and piece.language == self.target)):
                self.targets.append(piece.text)
        self.partials = partials  # Non-final hypotheses replace, never append.
        if len(update.pieces) in boundaries:
            self.flush(now, "endpoint")
        if update.done:
            self.flush(now, "eof")

    def poll(self, now):
        if self.pending and self.last_text_at is not None and now - self.last_text_at >= self.idle_seconds:
            self.flush(now, "silence")

    def flush(self, now, boundary="eof"):
        if not self.pending:
            return
        pieces, self.pending = self.pending, []
        text = "".join(p.text for p in pieces).strip()
        if not text:
            return
        languages = {p.language for p in pieces if isinstance(p.language, str) and p.language in {"en", "ar"}}
        tag = "mix" if len(languages) == 2 else language_tag(text)
        speakers = sorted({p.speaker for p in pieces if isinstance(p.speaker, str)})
        starts, ends = [p.start_s for p in pieces], [p.end_s for p in pieces]
        start = min(starts) if all(v is not None for v in starts) else None
        end = max(ends) if all(v is not None for v in ends) else None
        self.entries.append({"source_text": text, "language_tag": tag,
            "source_language": "en" if tag == "en" else "ar", "vendor_languages": sorted(languages),
            "speakers": speakers, "pass_through": tag == self.target,
            "translated_text": text if tag == self.target else "", "mt_called": False,
            "asr_engine": "soniox", "mt_engine": "soniox", "target_language": self.target,
            "native_translation_unaligned": tag != self.target, "segment_boundary": boundary,
            "audio_start_s": start, "audio_end_s": end,
            "source_final_s": now - self.origin if self.origin is not None else None,
            "speech_end_latency_s": None, "latency_timing_status": "native target unaligned"})
