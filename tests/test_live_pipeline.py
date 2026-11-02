from dataclasses import replace
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from audio_processing import AudioChunkResult
from engines.conversation_pipeline import ConversationPipeline
from engines.live_pipeline import LiveConversationPipeline
from engines.router import Conversation
from engines.types import AsrResult, MtResult


def setup(*, mode="listen", conversation=None):
    clock = [0.0]
    events, transcripts = [], []
    stop = threading.Event()
    player = Mock()
    recognizer = SimpleNamespace(transcribe=Mock(return_value=AsrResult("نراجع الخادم.", "ar", .9, "ar", 0, -.2, 0, 1, "fixture-asr")))
    translator = SimpleNamespace(translate=Mock(return_value=MtResult("Review the server.", "fixture-mt")))
    fallback = ConversationPipeline(recognizer, translator, conversation or Conversation(), mode=mode,
        emit=lambda kind, data: events.append((kind, data)), transcripts=transcripts, stop_event=stop, speech_player=player)
    fallback.assembler.clock = lambda: clock[0]
    interpreter = SimpleNamespace(name="gemini-live", start=Mock(), push_audio=Mock(return_value=True), stop=Mock())
    lid = SimpleNamespace(detect=Mock(return_value=SimpleNamespace(language="ar")))
    pipeline = LiveConversationPipeline(fallback, interpreter, lid=lid, clock=lambda: clock[0])
    pipeline.start()
    def event(kind, **data):
        pipeline.events.put((kind, data))
    return SimpleNamespace(pipeline=pipeline, interpreter=interpreter, fallback=fallback, lid=lid,
                            recognizer=recognizer, translator=translator, player=player, stop=stop,
                            transcripts=transcripts, clock=clock, events=events, event=event)


def chunk():
    return AudioChunkResult("audio", np.ones(16000, np.float32) * .1, 16000, .1, .1)


def test_listen_english_is_source_only_and_never_translated_or_spoken():
    item = setup()
    item.event("input_transcription", text="The API works.", language="en", finished=True)
    item.event("audio", pcm=b"\x00\x00" * 2400, rate=24000)
    item.pipeline.poll()
    entry = item.transcripts[0]
    assert entry["source_text"] == "The API works." and entry["pass_through"] and not entry["mt_called"]
    assert not entry["translated_text"] and not entry["translation_pending"]
    item.translator.translate.assert_not_called()
    item.player.play_stream.assert_not_called()


def test_late_arabic_translation_is_not_discarded_at_first_idle_deadline():
    item = setup()
    item.event("input_transcription", text="نراجع API.", language="ar", finished=True)
    item.pipeline.poll()
    entry = item.transcripts[0]
    assert entry["translation_pending"] and entry["source_text"]
    item.clock[0] = 2
    item.pipeline.poll()
    assert entry["translation_pending"]
    item.event("output_transcription", text="Review API.", language="en", finished=True)
    item.pipeline.poll()
    assert entry["translated_text"] == "Review API." and not entry["translation_pending"]
    assert entry["language_tag"] == "mix" and entry["engine"] == "gemini-live"
    item.recognizer.transcribe.assert_not_called()
    item.translator.translate.assert_not_called()


def test_two_input_sentences_and_delayed_output_use_their_existing_rows():
    item = setup()
    item.event("input_transcription", text="مرحبا.", language="ar", finished=True)
    item.event("input_transcription", text="كيف الحال؟", language="ar", finished=True)
    item.event("output_transcription", text="Hello.", finished=True)
    item.event("output_transcription", text="How are you?", finished=True)
    item.pipeline.poll()
    assert [row["translated_text"] for row in item.transcripts] == ["Hello.", "How are you?"]


def test_orphan_target_is_retained_until_source_arrives_and_late_suffix_is_preserved():
    item = setup()
    item.event("output_transcription", text="Review", finished=False)
    item.event("input_transcription", text="نراجع الخادم.", language="ar", finished=True)
    item.pipeline.poll()
    item.clock[0] = 2
    item.pipeline.poll()
    item.event("output_transcription", text=" the server.", finished=True)
    item.pipeline.poll()
    assert item.transcripts[0]["translated_text"] == "Review the server."


def test_speak_english_streams_24k_audio_even_after_target_text_was_finished():
    item = setup(mode="speak")
    item.event("input_transcription", text="The deployment is ready.", language="en", finished=True)
    item.event("output_transcription", text="التجهيز جاهز.", language="ar", finished=True)
    item.event("audio", pcm=b"\x01\x00" * 2400, rate=24000)
    item.pipeline.poll()
    item.player.play_stream.assert_called_once_with(b"\x01\x00" * 2400, rate=24000)
    item.player.enqueue.assert_not_called()


@pytest.mark.parametrize("policy,raw_calls,tts_calls", [("passthrough", 1, 0), ("mute", 0, 0), ("voice", 0, 1)])
def test_speak_arabic_uses_original_voice_mute_or_voice_setting(policy, raw_calls, tts_calls):
    item = setup(mode="speak", conversation=Conversation(same_language_speech=policy))
    item.pipeline.push_capture(np.zeros((4800, 2), np.float32), 48000)
    uploaded = item.interpreter.push_audio.call_args.args[0]
    assert uploaded.shape == (1600,)
    item.pipeline.feed(item.pipeline.mark_chunk(chunk()))
    item.event("input_transcription", text="نراجع deployment.", language="ar", finished=True)
    item.event("audio", pcm=b"\x00\x00" * 2400, rate=24000)
    item.pipeline.poll()
    assert item.player.play_stream.call_count == raw_calls
    assert item.player.enqueue.call_count == tts_calls
    assert item.transcripts[0]["pass_through"] and not item.transcripts[0]["mt_called"]
    item.recognizer.transcribe.assert_not_called()


def test_reconnect_clears_old_audio_and_fresh_session_marks_unfinished_row():
    item = setup(mode="speak")
    item.event("input_transcription", text="The deployment", language="en", finished=False)
    item.event("reconnecting")
    item.event("connected", resumed=False, offset_s=1.2)
    item.pipeline.poll()
    item.player.reset_stream.assert_called_once()
    assert item.transcripts[0]["translation_interrupted"]
    assert item.pipeline.transport_base == 1.2


def test_no_target_timeout_recovers_unconfirmed_audio_then_processes_new_chunks_in_free():
    item = setup()
    original = chunk()
    item.pipeline.feed(original)
    item.event("input_transcription", text="مرحبا.", language="ar", finished=True)
    item.pipeline.poll()
    item.clock[0] = 8.1
    item.pipeline.poll()
    assert not item.pipeline.live
    item.recognizer.transcribe.assert_called_once()
    assert item.recognizer.transcribe.call_args.args[0] is original.samples
    item.pipeline.feed(chunk())
    assert item.recognizer.transcribe.call_count == 2
    assert any(kind == "hint" and "overlapping" in data for kind, data in item.events)


def test_source_offsets_prune_confirmed_chunks_and_stop_preserves_only_queued_text():
    item = setup(mode="speak")
    item.pipeline.push_capture(np.zeros(1600, np.float32), 16000)
    item.pipeline.feed(item.pipeline.mark_chunk(chunk()))
    item.event("input_transcription", text="نعم.", language="ar", finished=True, end_offset="0.1s")
    item.pipeline.poll()
    assert not item.pipeline.retained
    before = item.player.play_stream.call_count
    item.event("input_transcription", text="The next line", language="en", finished=False)
    item.event("audio", pcm=b"\x01\x00" * 2400, rate=24000)
    item.stop.set()
    item.pipeline.cancel()
    assert item.player.play_stream.call_count == before
    assert item.transcripts[-1]["source_text"] == "The next line" and item.transcripts[-1]["translation_cancelled"]
    assert not item.pipeline.retained and not item.pipeline.pending


def test_both_language_captions_use_shared_mt_only_when_requested():
    item = setup(conversation=Conversation(show_both=True))
    item.event("input_transcription", text="The API works.", language="en", finished=True)
    item.pipeline.poll()
    item.clock[0] = 2
    item.pipeline.poll()
    item.translator.translate.assert_called_once()
    row = item.transcripts[0]
    assert row["secondary_translation"] and row["mt_called"] and row["target_language"] == "ar"


def test_lost_protected_term_uses_free_mt_and_voice_instead_of_native_audio(tmp_path):
    from engines.glossary import Glossary
    item = setup(mode="speak")
    item.fallback.glossary = Glossary(tmp_path / "terms.json", read_only=True)
    item.translator.translate.return_value = MtResult("deployment يعمل.", "fixture-mt")
    item.event("input_transcription", text="The deployment works.", language="en", finished=True)
    item.event("audio", pcm=b"\x01\x00" * 2400, rate=24000)
    item.pipeline.poll()
    item.player.play_stream.assert_not_called()
    item.event("output_transcription", text="النشر يعمل.", language="ar", finished=True)
    item.event("audio", pcm=b"\x02\x00" * 2400, rate=24000)
    item.pipeline.poll()
    item.translator.translate.assert_called_once()
    item.player.play_stream.assert_not_called()
    item.player.enqueue.assert_called_once_with("deployment يعمل.", "ar", "Automatic")
    assert item.transcripts[0]["translated_text"] == "deployment يعمل."
    assert item.transcripts[0]["mt_engine"] == "fixture-mt"


def test_input_back_transliteration_and_both_scripts_are_kept_in_source(tmp_path):
    from engines.glossary import Glossary
    item = setup()
    item.fallback.glossary = Glossary(tmp_path / "terms.json", read_only=True)
    item.event("input_transcription", text="نراجع ربليكا.", language="ar", finished=True)
    item.event("output_transcription", text="Review replica.", finished=True)
    item.pipeline.poll()
    assert item.transcripts[0]["source_text"] == "نراجع replica."
    assert item.transcripts[0]["language_tag"] == "mix"
