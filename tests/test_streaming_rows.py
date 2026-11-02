"""Synthetic timing and token ordering, not recorded vendor sessions."""
import threading
from types import SimpleNamespace

import pytest

from engines.provider import ProviderError
from engines.types import MtResult
from tools.eval.metrics import score_clip
from tools.eval.streaming_protocols import ElevenLabsProtocol, SonioxProtocol, StreamPiece
from tools.eval.streaming_rows import CascadedRows, SonioxRows


def cascaded():
    clock, calls = [101.0], []
    glossary = SimpleNamespace(restore_english=lambda text: (text, 0), translations=lambda: {})
    translator = SimpleNamespace(translate=lambda text, *a, **kw: (calls.append(text) or MtResult("Hello.", "fake")))
    rows = CascadedRows("elevenlabs", "en", translator, glossary, threading.Event(), clock=lambda: clock[0])
    return rows, clock, calls


def annotation(text, start, end, language="ar"):
    return StreamPiece(text, True, language=language, start_s=start, end_s=end)


def test_delayed_annotation_preserves_original_display_completion_and_never_translates_again():
    rows, clock, calls = cascaded()
    rows.feed(StreamPiece("مرحبا.", True), 100)
    clock[0] = 105  # Metadata arrives four seconds after the displayed translation.
    rows.annotate(annotation("مرحبا.", .1, .8), 100)
    observed, expected = rows.finish_timing(2)
    assert observed == pytest.approx([.2]) and expected == 1
    assert calls == ["مرحبا."] and rows.entries[0]["speech_end_at"] == 100.8


def test_merged_sentence_uses_last_source_interval_and_requires_every_commit():
    rows, clock, calls = cascaded()
    rows.feed(StreamPiece("نراجع API", True), 100)
    rows.feed(StreamPiece("بعد meeting", True), 100)
    clock[0] = 102
    rows.pipeline.flush()
    rows.annotate(annotation("نراجع API", .1, .5), 100)
    assert rows.finish_timing(3)[0] == []
    assert rows.entries[0]["speech_end_latency_s"] is None
    rows.annotate(annotation("بعد meeting", 1, 1.5), 100)
    assert rows.finish_timing(3)[0] == pytest.approx([.5])
    assert calls == ["نراجع API بعد meeting"]


def test_identical_repeated_utterances_join_complete_interval_groups_in_audio_order():
    rows, clock, calls = cascaded()
    rows.feed(StreamPiece("مرحبا.", True), 100)
    clock[0] = 102
    rows.feed(StreamPiece("مرحبا.", True), 100)
    second = annotation("مرحبا.", 1, 1.5)
    rows.annotate(second, 100)  # Later interval is delivered first.
    rows.annotate(second, 100)  # Duplicate transport delivery.
    assert rows.finish_timing(3)[0] == []  # Can't guess which commit a lone interval describes.
    rows.annotate(annotation("مرحبا.", 0, .5), 100)
    assert rows.finish_timing(3)[0] == pytest.approx([.5, .5])
    assert len(calls) == 2


def test_conflicting_metadata_and_changed_text_stay_unjoined():
    rows, _, calls = cascaded()
    rows.feed(StreamPiece("مرحبا.", True), 100)
    rows.annotate(annotation("مرحبا.", 0, .5, "ar"), 100)
    rows.annotate(annotation("مرحبا.", 0, .5, "en"), 100)
    rows.annotate(annotation("مرحبا", 0, .5), 100)  # Text doesn't match its commit.
    assert rows.finish_timing(2)[0] == [] and len(calls) == 1


def test_future_or_out_of_clip_timing_cannot_make_a_provider_appear_fast():
    rows, _, _ = cascaded()
    rows.feed(StreamPiece("مرحبا.", True), 100)
    rows.annotate(annotation("مرحبا.", .1, 4), 100)
    assert rows.finish_timing(3)[0] == [] and rows.errors
    rows, _, _ = cascaded()
    rows.feed(StreamPiece("مرحبا.", True), 100)
    rows.annotate(annotation("مرحبا.", .1, 1.5), 100)  # Ends after displayed completion at 101.
    assert rows.finish_timing(3)[0] == []


def test_elevenlabs_metadata_uses_word_intervals_and_iso_alias_without_a_second_piece():
    result = ElevenLabsProtocol().parse({"message_type": "committed_transcript_with_timestamps",
        "text": "راجع API", "language_code": "ara", "words": [
            {"text": "راجع", "type": "word", "start": .2, "end": .5, "speaker_id": "speaker_1"},
            {"text": " ", "type": "spacing", "start": .5, "end": 9},
            {"text": "API", "type": "word", "start": .6, "end": .8, "speaker_id": "speaker_1"}]})
    assert not result.pieces and len(result.annotations) == 1
    piece = result.annotations[0]
    assert piece.start_s == .2 and piece.end_s == .8 and piece.language == "ar" and piece.speaker == "speaker_1"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -.1, True])
def test_invalid_vendor_word_timestamps_fail_without_echoing_payload(invalid):
    with pytest.raises(ProviderError) as caught:
        ElevenLabsProtocol().parse({"message_type": "committed_transcript_with_timestamps", "text": "PRIVATE",
                                   "words": [{"start": invalid, "end": 1}]})
    assert "PRIVATE" not in str(caught.value)


def test_missing_last_word_timing_does_not_use_an_earlier_word_as_speech_end():
    result = ElevenLabsProtocol().parse({"message_type": "committed_transcript_with_timestamps", "text": "hello API",
        "words": [{"text": "hello", "start": 0, "end": .2}, {"text": "API", "start": .3}]})
    assert result.annotations[0].end_s is None
    with pytest.raises(ProviderError):
        ElevenLabsProtocol().parse({"message_type": "committed_transcript_with_timestamps", "text": "bad",
                                   "words": [{"start": 1, "end": .5}]})


def test_soniox_multiple_endpoints_preserve_source_tags_but_do_not_invent_translation_pairs():
    tokens = [
        {"text": "Hello", "is_final": True, "language": "en", "translation_status": "none"},
        {"text": "<end>", "is_final": True},
        {"text": "نراجع ", "is_final": True, "language": "ar", "translation_status": "original"},
        {"text": "API", "is_final": True, "language": "en", "translation_status": "original"},
        {"text": "<end>", "is_final": True},
        {"text": " Check API", "is_final": True, "language": "en", "translation_status": "translation"}]
    protocol, rows = SonioxProtocol(), SonioxRows()
    update = protocol.parse({"tokens": tokens})
    assert update.boundaries == (1, 3)
    rows.push(update, 101, 100)
    assert [e["source_text"] for e in rows.entries] == ["Hello", "نراجع API"]
    assert [e["language_tag"] for e in rows.entries] == ["en", "mix"]
    assert rows.entries[0]["pass_through"] and rows.entries[1]["native_translation_unaligned"]
    assert rows.target_text == "Hello Check API"


def test_soniox_partial_revisions_are_replaced_and_never_committed_twice():
    protocol, rows = SonioxProtocol(), SonioxRows()
    rows.push(protocol.parse({"tokens": [
        {"text": "نراجع", "is_final": True, "language": "ar"},
        {"text": " WRONG", "is_final": False, "language": "en"}]}), 100, 100)
    rows.push(protocol.parse({"tokens": [{"text": " API", "is_final": False, "language": "en"}]}), 100.1, 100)
    assert rows.draft_source == "نراجع API" and not rows.entries
    rows.push(protocol.parse({"tokens": [
        {"text": " API", "is_final": True, "language": "en"}, {"text": "<end>", "is_final": True}]}), 100.2, 100)
    assert rows.entries[0]["source_text"] == "نراجع API" and not rows.draft_source


def test_soniox_silence_boundary_excludes_nonfinal_text_and_retains_later_finals():
    protocol, rows = SonioxProtocol(), SonioxRows()
    rows.push(protocol.parse({"tokens": [{"text": "مرحبا", "is_final": True, "language": "ar"},
                                          {"text": " draft", "is_final": False, "language": "en"}]}), 0, 0)
    rows.poll(1.19)
    assert not rows.entries
    rows.poll(1.2)
    assert rows.entries[0]["source_text"] == "مرحبا" and rows.entries[0]["segment_boundary"] == "silence"
    rows.push(protocol.parse({"tokens": [{"text": " API", "is_final": True, "language": "en"}], "finished": True}), 2, 0)
    assert [e["source_text"] for e in rows.entries] == ["مرحبا", "API"]


def test_per_tag_wer_uses_reference_groups_and_rejects_uncertain_row_alignment():
    entries = [{"source_text": "hello", "language_tag": "ar"},
               {"source_text": "مرحبا", "language_tag": "en"},
               {"source_text": "نراجع API", "language_tag": "mix"}]
    metrics = score_clip("hello\nمرحبا\nنراجع API deployment", "irrelevant", ["en", "ar", "mix"], entries)
    assert metrics["en_wer"] == 0 and metrics["ar_wer"] == 0
    assert metrics["mix_wer"] == pytest.approx(1 / 3) and metrics["mix_english_term_recall"] == .5
    missing = score_clip("hello\nمرحبا", "irrelevant", ["en", "ar"], entries)
    assert not missing["group_metrics_aligned"] and missing["ar_wer"] is None


def test_native_clip_target_override_does_not_require_fake_translated_rows():
    result = score_clip("hello\nمرحبا", "hello hi", ["en", "ar"],
        [{"source_text": "hello", "pass_through": True}, {"source_text": "مرحبا", "translated_text": ""}],
        hypothesis_target="hello hi")
    assert result["wer"] == 0 and result["chrf"] == 100


def test_profile_report_cannot_publish_p95_for_only_the_fast_measured_subset(tmp_path):
    from tools.eval.run_eval import write_reports
    base = score_clip("hello", "hello", ["en"], [{"source_text": "hello", "pass_through": True}])
    row = {**base, "profile": "speechmatics", "error_count": 0, "estimated_cost_usd": "0.01"}
    predictions = [
        {"processing_latencies_s": [], "speech_end_latencies_s": [.1], "latency_expected_rows": 1, "latency_measured_rows": 1},
        {"processing_latencies_s": [], "speech_end_latencies_s": [], "latency_expected_rows": 2, "latency_measured_rows": 1}]
    write_reports(tmp_path, [{"profile": "speechmatics", "rows": [row, row], "predictions": predictions,
                             "peak_rss_bytes": 0, "model_load_s": 0}], {"git_commit": "synthetic", "tracked_changes": True})
    summary = (tmp_path / "summary.md").read_text()
    table = next(line for line in summary.splitlines() if line.startswith("| speechmatics |"))
    assert table.split("|")[7].strip() == "n/a" and "2/3" in summary
