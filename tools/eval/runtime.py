"""Feed WAV samples through the desktop app, with no audio device or TTS.

No parallel reimplementation of segmentation, ASR, or MT lives in this tool.
The event records are also useful for diagnosing where a live result vanished.
"""
import atexit
from contextlib import contextmanager
import os
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


@contextmanager
def block_network():
    def denied(*args, **kwargs):
        raise RuntimeError("Network access blocked by offline evaluation")

    with patch.object(socket.socket, "connect", denied), \
            patch.object(socket.socket, "connect_ex", denied), \
            patch.object(socket, "create_connection", denied), \
            patch.object(socket, "getaddrinfo", denied):
        yield


class PeakMemory:
    def __enter__(self):
        import psutil
        self.process = psutil.Process()
        self.peak = 0
        self.done = threading.Event()
        self._sample()
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()
        return self

    def _sample(self):
        import psutil
        processes = [self.process] + self.process.children(recursive=True)
        rss = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.peak = max(self.peak, rss)

    def _poll(self):
        while not self.done.wait(0.05):
            self._sample()

    def __exit__(self, *args):
        self._sample()
        self.done.set()
        self.thread.join()


class ReplayClock:
    """Advance silent capture time instantly; retain real inference time/lag."""
    def __init__(self):
        self.advance(0.0)

    def __call__(self):
        return self.value + time.perf_counter() - self.wall

    def advance(self, value):
        self.value, self.wall = value, time.perf_counter()


class DesktopRuntime:
    def __init__(self, profile, *, source="ar", target="en",
                 whisper_model="openai/whisper-small", allow_network=False,
                 legacy_fixed_window=False, runtime_factory=None, runtime_kwargs=None):
        if profile not in {"baseline", "offline"}:
            raise ValueError(f"Profile {profile!r} is not implemented; it cannot be evaluated as local")
        if not allow_network:
            os.environ["OFFLINE_ONLY"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["WHISPER_MODEL"] = whisper_model
        if runtime_factory is None:
            from main import ArabicAudioTranscriber
            runtime_factory = ArabicAudioTranscriber
        self.events = []
        self.clock = ReplayClock()
        self.completed_at = {}
        options = dict(runtime_kwargs or {})
        if profile == "offline" and "en" in {source, target} and source != target:
            from engines.router import Conversation
            from engines.glossary import Glossary
            other = source if source != "en" else target
            options.setdefault("conversation", Conversation(other_language=other, my_language=target,
                                                            audience_language=other))
            # Read the current terms/defaults without creating or merging files
            # in the user's profile. Replay never changes app settings/data.
            options.setdefault("glossary", Glossary(read_only=True))
        self.runtime = runtime_factory(
            interactive=False, asr_language=source, target_language=target,
            translation_model=f"Helsinki-NLP/opus-mt-{source}-{target}",
            mode="listen", on_event=self._event, **options,
        )
        # Evaluation owns its output. Do not create auto-saved transcripts or
        # call start_background(), which writes user settings and opens devices.
        atexit.unregister(self.runtime.save_transcript)
        self.legacy_fixed_window = legacy_fixed_window or profile == "baseline"
        self.mt_calls = []
        self._translate = self.runtime.translate_text

        def measured_translate(text):
            self.mt_calls.append(text)
            return self._translate(text)

        self.runtime.translate_text = measured_translate
        pipeline = self.runtime.conversation_pipeline
        if pipeline is not None:
            self._pipeline_translate = pipeline.translator.translate

            def measured_bilingual(text, *args, **kwargs):
                self.mt_calls.append(text)
                return self._pipeline_translate(text, *args, **kwargs)

            pipeline.translator = SimpleNamespace(translate=measured_bilingual)
            pipeline.assembler.clock = self.clock

    def _event(self, kind, payload):
        self.events.append((time.perf_counter(), kind, payload))
        if kind == "transcript_update" and not payload.get("translation_pending"):
            self.completed_at.setdefault(payload["id"], self.clock())

    def evaluate(self, samples, sample_rate):
        processor = self.runtime.create_audio_processor(sample_rate=sample_rate)
        # P1 exposes a comparison flag. P0 already uses the legacy segmenter.
        if self.legacy_fixed_window and hasattr(processor, "legacy_fixed_window"):
            processor.legacy_fixed_window = True
        before = len(self.runtime.transcripts)
        self.events.clear()
        self.mt_calls.clear()
        self.completed_at.clear()
        latencies = []
        segment_count = 0
        block_size = max(1, round(sample_rate * 0.1))
        started = time.perf_counter()
        # First replay only capture/VAD, assigning each event its WAV time.
        # The second pass runs the actual desktop inference path. Slow ASR/MT
        # advances the simulated consumer clock while capture keeps arriving,
        # so retained backlog and sentence idle timers affect latency honestly.
        origin = time.monotonic()
        capture_time = [origin]
        processor.clock = lambda: capture_time[0]
        activity, timeline = [], []
        processor.on_speech = lambda value: activity.append(value)
        for offset in range(0, len(samples), block_size):
            capture_time[0] = origin + min(offset + block_size, len(samples)) / sample_rate
            for result in processor.append(samples[offset:offset + block_size], sample_rate):
                timeline.append((capture_time[0], result))
        for result in processor.flush():
            timeline.append((capture_time[0], result))
        timeline.extend((value, None) for value in activity)
        timeline.sort(key=lambda item: item[0])
        self.clock.advance(origin)
        pipeline = self.runtime.conversation_pipeline
        if pipeline is not None:
            pipeline.context.clear()
            pipeline.last_speech_at = None
            if hasattr(pipeline.recognizer, "lid"):
                pipeline.recognizer.lid.previous = None
        activity_index = 0

        def notify_current_speech():
            nonlocal activity_index
            while activity_index < len(activity) and activity[activity_index] <= self.clock():
                if pipeline is not None:
                    pipeline.notify_speech(activity[activity_index])
                activity_index += 1

        for arrival, result in timeline:
            while pipeline is not None and pipeline.assembler.pending and self.clock() < arrival:
                due = pipeline.assembler.updated_at + pipeline.assembler.idle_seconds
                if due > arrival:
                    break
                self.clock.advance(max(self.clock(), due))
                notify_current_speech()
                pipeline.poll()
            self.clock.advance(max(self.clock(), arrival))
            notify_current_speech()
            if result is None:
                if pipeline is not None:
                    pipeline.poll()
                continue
            self.runtime._handle_capture_result(result)
            if result.kind != "audio":
                continue
            segment_count += 1
            begin = time.perf_counter()
            old_count, old_calls = len(self.runtime.transcripts), len(self.mt_calls)
            if pipeline is not None:
                pipeline.feed(self.runtime.audio_queue.get_nowait())
                notify_current_speech()
                pipeline.poll()
            else:
                self.runtime.process_audio()
                for entry in self.runtime.transcripts[old_count:]:
                    entry["mt_called"] = len(self.mt_calls) > old_calls
            latencies.append(time.perf_counter() - begin)
        if pipeline is not None:
            # EOF models ending capture normally; flush the final sentence once.
            self.clock.advance(max(self.clock(), origin + len(samples) / sample_rate))
            pipeline.flush()
        elapsed = time.perf_counter() - started
        entries = [entry.copy() for entry in self.runtime.transcripts[before:]]
        for entry in entries:
            completed = self.completed_at.get(entry["id"])
            captured, ended = entry.get("captured_at"), entry.get("speech_end_at")
            entry["processing_latency_s"] = max(0, completed - captured) if completed is not None and captured is not None else None
            entry["speech_end_latency_s"] = max(0, completed - ended) if completed is not None and ended is not None else None
        errors = [payload for _, kind, payload in self.events if kind == "error"]
        return {
            "entries": entries, "segment_count": segment_count,
            "processing_latencies_s": latencies,
            "speech_end_latencies_s": [e["speech_end_latency_s"] for e in entries
                                        if e.get("speech_end_latency_s") is not None],
            "elapsed_s": elapsed, "mt_characters": sum(map(len, self.mt_calls)),
            "mt_requests": len(self.mt_calls), "errors": errors,
            "latency_method": "WAV capture clock with measured inference time, retained backlog and EOF flush",
        }
