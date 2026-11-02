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


class DesktopRuntime:
    def __init__(self, profile, *, source="ar", target="en",
                 whisper_model="openai/whisper-small", allow_network=False,
                 legacy_fixed_window=False, runtime_factory=None):
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
        self.runtime = runtime_factory(
            interactive=False, asr_language=source, target_language=target,
            translation_model=f"Helsinki-NLP/opus-mt-{source}-{target}",
            mode="listen", on_event=self._event,
        )
        # Evaluation owns its output. Do not create auto-saved transcripts or
        # call start_background(), which writes user settings and opens devices.
        atexit.unregister(self.runtime.save_transcript)
        self.legacy_fixed_window = legacy_fixed_window
        self.mt_calls = []
        self._translate = self.runtime.translate_text

        def measured_translate(text):
            self.mt_calls.append(text)
            return self._translate(text)

        self.runtime.translate_text = measured_translate

    def _event(self, kind, payload):
        self.events.append((time.perf_counter(), kind, payload))

    def evaluate(self, samples, sample_rate):
        processor = self.runtime.create_audio_processor(sample_rate=sample_rate)
        # P1 exposes a comparison flag. P0 already uses the legacy segmenter.
        if self.legacy_fixed_window and hasattr(processor, "legacy_fixed_window"):
            processor.legacy_fixed_window = True
        before = len(self.runtime.transcripts)
        self.events.clear()
        self.mt_calls.clear()
        latencies = []
        segment_count = 0
        block_size = max(1, round(sample_rate * 0.1))
        started = time.perf_counter()

        def consume(result):
            nonlocal segment_count
            if result.kind != "audio":
                return
            segment_count += 1
            begin = time.perf_counter()
            old_count = len(self.runtime.transcripts)
            old_calls = len(self.mt_calls)
            self.runtime._handle_capture_result(result)
            self.runtime.process_audio()
            elapsed = time.perf_counter() - begin
            # End-of-speech latency includes the endpointing silence, when the
            # segmenter supplies it. Legacy P0 reports processing latency only.
            endpoint_delay = getattr(result, "endpoint_delay_s", None)
            for entry in self.runtime.transcripts[old_count:]:
                entry["mt_called"] = len(self.mt_calls) > old_calls
                entry["processing_latency_s"] = elapsed
                entry["speech_end_latency_s"] = (
                    elapsed + endpoint_delay if endpoint_delay is not None else None)
            latencies.append(elapsed)

        for offset in range(0, len(samples), block_size):
            for result in processor.append(samples[offset:offset + block_size], sample_rate):
                consume(result)
        for result in processor.flush():
            consume(result)
        if hasattr(self.runtime, "flush_sentences"):
            self.runtime.flush_sentences()
        elapsed = time.perf_counter() - started
        entries = [entry.copy() for entry in self.runtime.transcripts[before:]]
        errors = [payload for _, kind, payload in self.events if kind == "error"]
        return {
            "entries": entries, "segment_count": segment_count,
            "processing_latencies_s": latencies,
            "speech_end_latencies_s": [e["speech_end_latency_s"] for e in entries
                                        if e.get("speech_end_latency_s") is not None],
            "elapsed_s": elapsed, "mt_characters": sum(map(len, self.mt_calls)),
            "mt_requests": len(self.mt_calls), "errors": errors,
        }
