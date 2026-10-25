import queue
import threading

import numpy as np

from audio_processing import AudioChunkResult
from main import ArabicAudioTranscriber


def worker():
    transcriber = ArabicAudioTranscriber.__new__(ArabicAudioTranscriber)
    transcriber.running = False
    transcriber.audio_queue = queue.Queue(maxsize=1)
    transcriber._stop_event = threading.Event()
    transcriber._last_backlog_hint_time = 0.0
    transcriber._last_empty_text_hint_time = 0.0
    transcriber.audio_debug = False
    transcriber.offline_only = False
    transcriber.sample_rate = 16000
    transcriber.whisper_language = "ar"
    transcriber.translation_target_language = "en"
    transcriber.mode = "listen"
    transcriber.speech_player = None
    transcriber.transcripts = []
    events = []
    transcriber.on_event = lambda kind, payload: events.append((kind, payload))
    return transcriber, events


def chunk(value=0.2):
    return AudioChunkResult("audio", np.full(16000, value, dtype=np.float32),
                            16000, value, value, "Test loopback")


def test_source_is_published_before_translation_and_final_result_updates_same_entry():
    transcriber, events = worker()
    transcriber.audio_queue.put(chunk())
    transcriber.recognize_speech_offline = lambda samples: "مرحبا"

    def translate(text):
        partial = [payload for kind, payload in events if kind == "transcript"]
        assert len(partial) == 1
        assert partial[0]["source_text"] == text
        assert partial[0]["translation_pending"] is True
        assert partial[0]["translated_text"] == ""
        return "Hello"

    transcriber.translate_text = translate
    transcriber.process_audio()

    partial = next(payload for kind, payload in events if kind == "transcript")
    final = next(payload for kind, payload in events if kind == "transcript_update")
    assert partial["translation_pending"] is True
    assert final["id"] == partial["id"]
    assert final["translation_pending"] is False
    assert final["translated_text"] == "Hello"
    assert len(transcriber.transcripts) == 1
    assert transcriber.transcripts[0]["translated_text"] == "Hello"


def test_translation_error_keeps_recognized_speech_visible():
    transcriber, events = worker()
    transcriber.audio_queue.put(chunk())
    transcriber.recognize_speech_offline = lambda samples: "مرحبا"

    def fail(text):
        raise RuntimeError("translator unavailable")

    transcriber.translate_text = fail
    transcriber.process_audio()

    assert transcriber.transcripts[0]["source_text"] == "مرحبا"
    final = next(payload for kind, payload in events if kind == "transcript_update")
    assert final["translation_pending"] is False
    assert final["translation_error"] == "translator unavailable"
    assert any(kind == "error" for kind, _ in events)


def test_live_capture_keeps_only_latest_waiting_chunk():
    transcriber, _ = worker()
    transcriber._handle_capture_result(chunk(0.2))
    newest = chunk(0.3)
    transcriber._handle_capture_result(newest)

    assert transcriber.audio_queue.qsize() == 1
    assert transcriber.audio_queue.get_nowait() is newest


def test_stop_cancels_generation_and_discards_waiting_audio():
    transcriber, _ = worker()
    transcriber.audio_queue.put(chunk())
    criteria = transcriber._generation_stopping_criteria()[0]
    assert criteria(None, None) is False

    transcriber.stop_background()

    assert criteria(None, None) is True
    assert transcriber.audio_queue.empty()
    transcriber._handle_capture_result(chunk())
    assert transcriber.audio_queue.empty()
