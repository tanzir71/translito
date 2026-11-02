import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from audio_processing import AudioChunkResult
from engines.conversation_pipeline import ConversationPipeline
from engines.lid import latin_ratio
from engines.router import Conversation
from engines.sentence_assembler import SentenceAssembler
from engines.types import AsrResult, MtResult


def recognized(text, tag):
    return AsrResult(text, "ar" if tag == "mix" else tag, 0.9, tag,
                     latin_ratio(text), -0.2, 0, 2, "fake-asr")


def chunk(value=0.2):
    return AudioChunkResult("audio", np.full(32000, value, dtype=np.float32), 16000, value, value)


def pipeline(results, conversation=None, mode="listen", **kwargs):
    events, entries = [], []
    recognizer = Mock()
    recognizer.transcribe.side_effect = results
    translator = Mock()
    translator.translate.return_value = MtResult("Translated.", "fake-mt")
    player = Mock()
    instance = ConversationPipeline(recognizer, translator, conversation or Conversation(),
                                    mode=mode, emit=lambda k, p: events.append((k, p)),
                                    transcripts=entries, stop_event=threading.Event(),
                                    speech_player=player, **kwargs)
    return instance, translator, player, entries, events


def test_english_listen_is_visible_without_mt_or_target_line():
    runtime, translator, player, entries, events = pipeline([recognized("The API works.", "en")])
    runtime.feed(chunk())
    assert entries[0]["source_text"] == "The API works."
    assert entries[0]["pass_through"] and not entries[0]["translation_pending"]
    assert entries[0]["translated_text"] == ""
    assert entries[0]["mt_called"] is False
    translator.translate.assert_not_called()
    player.enqueue.assert_not_called()


def test_empty_recognition_returns_to_listening_and_shows_a_rate_limited_hint():
    runtime, translator, _, entries, events = pipeline([recognized("", "ar"), recognized("", "ar")])
    runtime.feed(chunk())
    runtime.feed(chunk())
    assert entries == []
    assert [payload for kind, payload in events if kind == "status"][-1] == "listening"
    assert sum(kind == "hint" for kind, _ in events) == 1
    translator.translate.assert_not_called()


def test_source_parts_update_one_row_before_sentence_translation():
    runtime, translator, player, entries, events = pipeline(
        [recognized("نراجع", "ar"), recognized("الخادم.", "ar")])
    runtime.feed(chunk())
    assert len(entries) == 1 and entries[0]["translation_pending"]
    translator.translate.assert_not_called()

    def translate(text, source, target, **kwargs):
        assert entries[0]["source_text"] == "نراجع الخادم."
        assert any(kind == "transcript_update" and payload["source_text"] == text
                   for kind, payload in events)
        return MtResult("Review the server.", "fake-mt")

    translator.translate.side_effect = translate
    runtime.feed(chunk())
    assert len(entries) == 1
    assert entries[0]["translated_text"] == "Review the server."
    assert not entries[0]["translation_pending"]
    assert translator.translate.call_count == 1


def test_language_change_creates_new_source_row_before_flushing_old_translation():
    runtime, translator, player, entries, events = pipeline(
        [recognized("مرحبا", "ar"), recognized("The API works.", "en")])
    runtime.feed(chunk())

    def translate(*args, **kwargs):
        assert len(entries) == 2
        assert entries[1]["source_text"] == "The API works."
        return MtResult("Hello", "fake-mt")

    translator.translate.side_effect = translate
    runtime.feed(chunk())
    assert entries[0]["translated_text"] == "Hello"
    assert entries[1]["mt_called"] is False
    assert translator.translate.call_count == 1


@pytest.mark.parametrize("tag", ["ar", "mix"])
def test_speak_arabic_or_mixed_passes_buffered_voice_without_mt_or_tts(tag):
    runtime, translator, player, entries, events = pipeline([recognized("نراجع API", tag)], mode="speak")
    audio = chunk()
    runtime.feed(audio)
    translator.translate.assert_not_called()
    player.enqueue.assert_not_called()
    np.testing.assert_array_equal(player.enqueue_audio.call_args.args[0], audio.samples)
    assert player.enqueue_audio.call_args.args[1] == 16000


def test_mute_and_voice_choices_are_respected():
    muted, _, player, _, _ = pipeline([recognized("مرحبا", "ar")], mode="speak",
                                      conversation=Conversation(same_language_speech="mute"))
    muted.feed(chunk())
    player.enqueue.assert_not_called()
    player.enqueue_audio.assert_not_called()
    voiced, translator, player, _, _ = pipeline([recognized("مرحبا", "ar")], mode="speak",
                                               conversation=Conversation(same_language_speech="voice"))
    voiced.feed(chunk())
    player.enqueue.assert_called_once_with("مرحبا", "ar", "Automatic")
    translator.translate.assert_not_called()


def test_translation_error_or_stop_retains_source_and_prevents_late_speech():
    runtime, translator, player, entries, _ = pipeline([recognized("Hello.", "en")], mode="speak")
    translator.translate.side_effect = RuntimeError("Translator unavailable")
    runtime.feed(chunk())
    assert entries[0]["source_text"] == "Hello."
    assert entries[0]["translation_error"] == "Translator unavailable"
    player.enqueue.assert_not_called()
    cancelled, translator, player, entries, _ = pipeline([recognized("Hello.", "en")], mode="speak")
    translator.translate.side_effect = lambda *a, **kw: cancelled.stop_event.set() or MtResult("مرحبا", "fake")
    cancelled.feed(chunk())
    assert entries[0]["translation_cancelled"]
    player.enqueue.assert_not_called()


def test_timeout_flush_and_cancel_pending_sentence():
    now = [0.0]
    assembler = SentenceAssembler(clock=lambda: now[0])
    runtime, translator, _, entries, _ = pipeline([recognized("مرحبا", "ar")], assembler=assembler)
    runtime.feed(chunk())
    now[0] = 1.5
    runtime.poll()
    translator.translate.assert_called_once()
    assert not entries[0]["translation_pending"]
    cancelled, translator, _, entries, _ = pipeline([recognized("مرحبا", "ar")])
    cancelled.feed(chunk())
    cancelled.cancel()
    assert entries[0]["translation_cancelled"]
    translator.translate.assert_not_called()


def test_capture_speech_resets_timeout_but_slow_asr_adds_no_artificial_wait():
    from dataclasses import replace
    import time
    now = [0.0]
    assembler = SentenceAssembler(clock=lambda: now[0])
    runtime, translator, _, entries, _ = pipeline([recognized("مرحبا", "ar")], assembler=assembler)
    runtime.feed(chunk())
    runtime.notify_speech(0.8)
    now[0] = 1.5
    runtime.poll()
    translator.translate.assert_not_called()
    now[0] = 2.31
    runtime.poll()
    translator.translate.assert_called_once()
    delayed, translator, _, _, _ = pipeline([recognized("مرحبا", "ar")])
    delayed.feed(replace(chunk(), captured_at=time.monotonic() - 3, endpoint_delay_s=0.6))
    delayed.poll()
    translator.translate.assert_called_once()


def test_both_languages_is_an_explicit_secondary_translation():
    runtime, translator, _, entries, _ = pipeline([recognized("Hello.", "en")],
                                                 conversation=Conversation(show_both=True))
    runtime.feed(chunk())
    assert entries[0]["secondary_translation"]
    assert entries[0]["target_language"] == "ar"
    assert translator.translate.call_args.args[:3] == ("Hello.", "en", "ar")


def test_secondary_translation_does_not_use_reverse_direction_context():
    runtime, translator, _, _, _ = pipeline([recognized("مرحبا.", "ar"), recognized("Hello.", "en")],
                                            conversation=Conversation(show_both=True))
    runtime.feed(chunk())
    runtime.feed(chunk())
    assert translator.translate.call_args.kwargs["context"] == []
    assert len(runtime.context) == 1
