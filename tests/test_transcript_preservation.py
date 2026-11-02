from datetime import datetime
from pathlib import Path

from main import ArabicAudioTranscriber


def test_repeated_saves_preserve_existing_transcripts_and_keep_raw_text(tmp_path):
    runtime = ArabicAudioTranscriber.__new__(ArabicAudioTranscriber)
    runtime.session_start_time = datetime(2026, 11, 2, 12, 0, 0)
    runtime.transcript_folder = tmp_path
    runtime.selected_device = None
    runtime.mode = "listen"
    original = "هخلص deployment بعد meeting"
    runtime.transcripts = [{"timestamp": "2026-11-02T12:00:01", "source_text": original,
                            "language_tag": "mix", "source_language": "ar", "target_language": "en",
                            "translated_text": "I will finish deployment after meeting."},
                           {"timestamp": "2026-11-02T12:00:02", "source_text": "The API works.",
                            "source_language": "en", "target_language": "en", "pass_through": True}]
    existing = tmp_path / "transcript_20261102_120000.txt"
    existing.write_bytes(b"keep the old transcript byte for byte")
    first = Path(runtime.save_transcript())
    first_content = first.read_bytes()
    second = Path(runtime.save_transcript())
    assert first != second and first != existing
    assert existing.read_bytes() == b"keep the old transcript byte for byte"
    assert first.read_bytes() == first_content
    content = first.read_text(encoding="utf-8")
    assert "Source (mix): " + original in content
    assert "Target: (same as source)" in content
    assert "\u2068" not in content and "\u2069" not in content
