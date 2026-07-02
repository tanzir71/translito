import numpy as np

from speech_output import resample_audio


def test_resample_audio_changes_length_and_keeps_float32():
    audio = np.linspace(-0.5, 0.5, 48000, dtype=np.float32)

    resampled = resample_audio(audio, 48000, 16000)

    assert resampled.dtype == np.float32
    assert len(resampled) == 16000
    assert np.isclose(float(resampled[0]), -0.5)


def test_resample_audio_returns_same_array_shape_when_rates_match():
    audio = np.linspace(-0.25, 0.25, 100, dtype=np.float32)

    resampled = resample_audio(audio, 16000, 16000)

    assert resampled.dtype == np.float32
    assert np.array_equal(resampled, audio)
