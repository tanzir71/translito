import numpy as np
import pytest

from main import ArabicAudioTranscriber


def test_recognize_speech_passes_raw_audio_to_pipeline():
    calls = []

    def asr(payload, **kwargs):
        calls.append((payload, kwargs))
        if "raw" not in payload:
            raise ValueError('ASR input requires a "raw" key')
        return {"text": " مرحبا "}

    transcriber = ArabicAudioTranscriber.__new__(ArabicAudioTranscriber)
    transcriber.asr = asr
    transcriber.sample_rate = 16000
    transcriber.whisper_language = "ar"
    audio = np.array([0.1, -0.2], dtype=np.float64)

    assert transcriber.recognize_speech_offline(audio) == "مرحبا"
    assert len(calls) == 1
    payload, kwargs = calls[0]
    assert set(payload) == {"raw", "sampling_rate"}
    assert payload["sampling_rate"] == 16000
    np.testing.assert_array_equal(payload["raw"], audio.astype(np.float32))
    assert kwargs["generate_kwargs"]["language"] == "ar"
    assert kwargs["generate_kwargs"]["num_beams"] == 1
    assert kwargs["generate_kwargs"]["max_new_tokens"] == 32
    assert "no_speech_threshold" not in kwargs["generate_kwargs"]


def test_recognition_errors_are_not_hidden_by_decoding_the_chunk_again():
    calls = []

    def asr(payload, **kwargs):
        calls.append((payload.copy(), kwargs))
        samples = payload.pop("raw")
        sample_rate = payload.pop("sampling_rate")
        assert sample_rate == 16000
        assert samples.dtype == np.float32
        raise TypeError("generation failed after decoding")

    transcriber = ArabicAudioTranscriber.__new__(ArabicAudioTranscriber)
    transcriber.asr = asr
    transcriber.sample_rate = 16000
    transcriber.whisper_language = "ar"

    with pytest.raises(TypeError, match="generation failed"):
        transcriber.recognize_speech_offline(np.array([0.1], dtype=np.float32))
    assert len(calls) == 1
