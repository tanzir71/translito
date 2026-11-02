from decimal import Decimal
import json
import socket
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from engines.usage import Rate, estimate_cost
from tools.eval.metrics import repetition_loops, score_clip
from tools.eval.run_eval import find_clips, read_audio
from tools.eval.runtime import DesktopRuntime, block_network


def test_bilingual_metrics_count_missed_terms_and_unnecessary_translation():
    metrics = score_clip(
        "The API works\nراجع ال replica في dashboard", "The API works. Check the replica in dashboard.",
        ["en", "mix"],
        [{"source_text": "The API works", "translated_text": "The API works", "language_tag": "en",
          "mt_called": True},
         {"source_text": "راجع ال ربليكا في dashboard", "translated_text": "Check Rebecca in dashboard.",
          "language_tag": "ar", "mt_called": True}], {"replica": ["ربليكا"]})
    assert metrics["english_term_recall"] == 4 / 5
    assert metrics["transliteration_rate"] == 1
    assert metrics["transliteration_annotation_coverage"] == 1 / 5
    assert metrics["unnecessary_mt_rate"] == 1
    assert metrics["tag_accuracy"] == 0.5


def test_metrics_do_not_invent_transliteration_measurements_or_ignore_missing_rows():
    metrics = score_clip("deployment\nhello", "deployment\nhello", ["mix", "en"],
                         [{"source_text": "deployment", "pass_through": True,
                           "language_tag": "mix", "mt_called": False}])
    assert metrics["transliteration_rate"] is None
    assert metrics["english_term_recall"] == 0.5
    assert metrics["tag_accuracy"] == 0.5
    assert metrics["unnecessary_mt_rate"] == 0


def test_repetition_metric_counts_maximal_ngrams():
    assert repetition_loops("نحن " * 300) == 1
    assert repetition_loops("hello there " * 5 + "done") == 1
    assert repetition_loops("one two three four " * 4) == 1
    assert repetition_loops("نحن نحن نحن مختلف") == 0


def test_usage_estimates_apply_per_request_audio_minimum():
    rate = Rate(per_audio_hour=Decimal("0.111"), minimum_audio_seconds=10)
    assert estimate_cost(rate, audio_seconds=6, requests=2) == Decimal("0.111") * 20 / 3600
    assert estimate_cost(Rate(per_million_chars=Decimal("10")), characters=50_000) == Decimal("0.5")
    with pytest.raises(ValueError):
        estimate_cost(rate, audio_seconds=float("nan"))


def test_sidecars_require_references_and_preserve_private_paths(tmp_path):
    wav = tmp_path / "sample.wav"
    wav.write_bytes(b"audio")
    with pytest.raises(ValueError, match="Missing reference"):
        find_clips(tmp_path)
    wav.with_suffix(".ref.src.txt").write_text("Hello\nمرحبا", encoding="utf-8")
    wav.with_suffix(".ref.tgt.txt").write_text("Hello\nHello", encoding="utf-8")
    wav.with_suffix(".ref.tag.txt").write_text("en\nar", encoding="utf-8")
    manifest = tmp_path / "sets.local.json"
    manifest.write_text(json.dumps({"clips": ["sample.wav"]}), encoding="utf-8")
    assert find_clips(manifest=manifest)[0]["tags"] == ["en", "ar"]
    wav.with_suffix(".ref.tag.txt").write_text("en", encoding="utf-8")
    with pytest.raises(ValueError, match="one tag per"):
        find_clips(tmp_path)


def test_wav_reader_resamples_stereo_and_handles_float_wav(tmp_path):
    import av
    pcm = tmp_path / "stereo.wav"
    with wave.open(str(pcm), "wb") as output:
        output.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        samples = np.full((48000, 2), 8000, dtype="<i2")
        output.writeframes(samples.tobytes())
    audio, rate = read_audio(pcm)
    assert rate == 16000
    assert len(audio) == 16000
    assert audio.dtype == np.float32
    float_wav = tmp_path / "float.wav"
    with av.open(str(float_wav), "w") as output:
        stream = output.add_stream("pcm_f32le", rate=16000)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(np.full((1, 16000), 0.25, dtype=np.float32),
                                          format="flt", layout="mono")
        frame.sample_rate = 16000
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    audio, rate = read_audio(float_wav)
    assert len(audio) == 16000
    np.testing.assert_allclose(audio, 0.25)


def test_offline_guard_blocks_dns_and_connections():
    with block_network():
        with pytest.raises(RuntimeError, match="blocked"):
            socket.getaddrinfo("example.com", 443)
        with socket.socket() as connection:
            with pytest.raises(RuntimeError, match="blocked"):
                connection.connect(("127.0.0.1", 1))


def test_replay_runs_desktop_events_without_capture_or_config_write(monkeypatch):
    import main
    from audio_processing import AudioChunkProcessor
    for key in ("OFFLINE_ONLY", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.setenv(key, "1")
    monkeypatch.setenv("WHISPER_MODEL", "openai/whisper-small")

    class Recognizer:
        def transcribe(self, audio, **kwargs):
            return "مرحبا"

    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, "load_models", lambda **kwargs:
                        SimpleNamespace(asr=Recognizer(), translator=lambda text, **kw:
                                        [{"translation_text": "Hello"}]))
    monkeypatch.setattr(main, "save_runtime_config", lambda *a, **kw: pytest.fail("Settings were written"))

    class AcceptSpeech:
        def contains_speech(self, audio, rate):
            return True

    original_processor = main.ArabicAudioTranscriber.create_audio_processor

    def processor(self, sample_rate=None):
        value = original_processor(self, sample_rate)
        assert isinstance(value, AudioChunkProcessor)
        value.speech_detector = AcceptSpeech()
        return value

    monkeypatch.setattr(main.ArabicAudioTranscriber, "create_audio_processor", processor)
    runtime = DesktopRuntime("baseline", runtime_factory=main.ArabicAudioTranscriber)
    with block_network():
        result = runtime.evaluate(np.concatenate([
            np.full(32000, 0.1, dtype=np.float32), np.zeros(12000, dtype=np.float32)]), 16000)
    assert result["segment_count"] == 1
    assert result["entries"][0]["source_text"] == "مرحبا"
    assert result["entries"][0]["translated_text"] == "Hello"
    assert result["entries"][0]["mt_called"]
    assert result["mt_requests"] == 1
    assert result["mt_characters"] == 5
    assert result["errors"] == []
    assert not runtime.runtime.running


def test_unknown_profile_is_never_silently_evaluated_as_local():
    with pytest.raises(ValueError, match="not implemented"):
        DesktopRuntime("free_cloud")


def test_offline_replay_uses_bilingual_assembly_and_english_no_mt(monkeypatch):
    import main
    from audio_processing import AudioChunkResult
    from engines.types import AsrResult, MtResult
    from unittest.mock import Mock
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, "load_models", lambda **kwargs:
                        SimpleNamespace(asr=Mock(), translator=Mock()))
    monkeypatch.setattr(main, "save_runtime_config", lambda *a, **kw: pytest.fail("Settings were written"))
    recognizer, translator = Mock(), Mock()
    translator.models = {}
    recognizer.name = translator.name = "fixture"
    recognizer.requires_network = translator.requires_network = False
    recognizer.transcribe.side_effect = [
        AsrResult(text, tag, .9, tag, float(tag == "en"), -.2, 0, .1, "fixture-asr")
        for text, tag in [("نراجع", "ar"), ("الخادم.", "ar"), ("The API works.", "en")]]
    translator.translate.return_value = MtResult("Review the server.", "fixture-mt")

    class Capture:
        step = 0
        def append(self, samples, rate):
            self.step += 1
            if self.step not in (1, 3, 6):
                return []
            self.on_speech(self.clock() - .032)
            return [AudioChunkResult("audio", samples, rate, .1, .1,
                                     captured_at=self.clock(), endpoint_delay_s=.032)]
        def flush(self):
            return []

    monkeypatch.setattr(main.ArabicAudioTranscriber, "create_audio_processor", lambda *a, **kw: Capture())
    with block_network():
        runtime = DesktopRuntime("offline", runtime_kwargs={"recognizer": recognizer, "translator_engine": translator})
        result = runtime.evaluate(np.full(16000, .1, dtype=np.float32), 16000)
    assert runtime.runtime.conversation is not None
    assert result["segment_count"] == 3 and len(result["entries"]) == 2
    assert result["entries"][0]["source_text"] == "نراجع الخادم."
    assert result["entries"][0]["segment_count"] == 2
    assert result["entries"][1]["pass_through"] and not result["entries"][1]["mt_called"]
    assert result["mt_requests"] == 1
    assert result["mt_characters"] == len("نراجع الخادم.")
    assert min(result["speech_end_latencies_s"]) >= .032
    translator.translate.assert_called_once()
    assert not runtime.runtime.running and result["errors"] == []


def test_offline_replay_sentence_timeout_uses_wav_silence_without_real_wait(monkeypatch):
    import main
    from audio_processing import AudioChunkResult
    from engines.types import AsrResult, MtResult
    from unittest.mock import Mock
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, "load_models", lambda **kwargs:
                        SimpleNamespace(asr=Mock(), translator=Mock()))
    recognizer, translator = Mock(), Mock()
    translator.models = {}
    recognizer.name = translator.name = "fixture"
    recognizer.requires_network = translator.requires_network = False
    recognizer.transcribe.side_effect = [AsrResult("مرحبا", "ar", .9, "ar", 0, -.2, 0, .1, "fixture")]
    translator.translate.return_value = MtResult("Hello", "fixture")
    class Capture:
        step = 0
        def append(self, samples, rate):
            self.step += 1
            if self.step == 1:
                self.on_speech(self.clock() - .032)
                return [AudioChunkResult("audio", samples, rate, .1, .1, captured_at=self.clock(), endpoint_delay_s=.032)]
            return []
        def flush(self):
            return []
    monkeypatch.setattr(main.ArabicAudioTranscriber, "create_audio_processor", lambda *a, **kw: Capture())
    runtime = DesktopRuntime("offline", runtime_kwargs={"recognizer": recognizer, "translator_engine": translator})
    # Keep a later capture event in the timeline; it must first service the
    # assembler's 1.5s deadline, rather than translating only at EOF.
    original = Capture.append
    def append(self, samples, rate):
        result = original(self, samples, rate)
        if self.step == 30:
            self.on_speech(self.clock())
        return result
    monkeypatch.setattr(Capture, "append", append)
    result = runtime.evaluate(np.full(48000, .1, dtype=np.float32), 16000)
    assert 1.5 <= result["entries"][0]["speech_end_latency_s"] < 2
    assert result["elapsed_s"] < 1
