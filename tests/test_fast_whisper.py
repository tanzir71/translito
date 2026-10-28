import threading
from types import SimpleNamespace

import numpy as np

from main import ArabicAudioTranscriber
from model_loading import FastWhisperASR, _local_fast_whisper_model


class FakeModel:
    def __init__(self):
        self.options = None

    def transcribe(self, audio, **options):
        self.options = options
        assert audio.dtype == np.float32
        return iter((SimpleNamespace(text=" تشكلت "), SimpleNamespace(text=" عاصفة "))), None


def test_fast_backend_transcribes_arabic_chunk():
    model = FakeModel()
    transcriber = ArabicAudioTranscriber.__new__(ArabicAudioTranscriber)
    transcriber.asr = FastWhisperASR(model)
    transcriber.whisper_language = "ar"
    transcriber._stop_event = threading.Event()

    text = transcriber.recognize_speech_offline(np.ones(16000, dtype=np.float64))

    assert text == "تشكلت عاصفة"
    assert model.options["language"] == "ar"
    assert model.options["task"] == "transcribe"
    assert model.options["condition_on_previous_text"] is False


def test_local_converted_model_is_used_when_complete(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSLITO_WHISPER_MODEL_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    folder = tmp_path / "Translito" / "models" / "whisper-small-ct2"
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"model")
    assert _local_fast_whisper_model("small") is None

    (folder / "config.json").write_text("{}", encoding="utf-8")
    assert _local_fast_whisper_model("small") is None
    (folder / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert _local_fast_whisper_model("small") == str(folder)
