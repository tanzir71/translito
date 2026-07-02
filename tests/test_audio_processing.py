import numpy as np

from audio_processing import AudioChunkProcessor, DROP_DIGITAL_SILENCE, DROP_NOISE_GATE


def test_emits_early_when_speech_is_followed_by_pause():
    sample_rate = 16000
    processor = AudioChunkProcessor(
        chunk_duration=6.0,
        input_sample_rate=sample_rate,
        target_sample_rate=sample_rate,
        noise_gate_rms=0,
    )
    speech = np.full(int(sample_rate * 1.6), 0.02, dtype=np.float32)
    pause = np.zeros(int(sample_rate * 0.75), dtype=np.float32)

    results = processor.append(np.concatenate([speech, pause]), sample_rate)

    audio_results = [result for result in results if result.kind == "audio"]
    assert len(audio_results) == 1
    assert 2.2 < audio_results[0].duration_seconds < 2.5
    assert processor.pending_frame_count == 0


def test_steady_ambient_noise_waits_for_the_full_window():
    sample_rate = 16000
    processor = AudioChunkProcessor(
        chunk_duration=6.0,
        input_sample_rate=sample_rate,
        target_sample_rate=sample_rate,
        noise_gate_rms=0,
    )
    first = np.full(int(sample_rate * 2.4), 0.006, dtype=np.float32)
    second = np.full(int(sample_rate * 3.6), 0.006, dtype=np.float32)

    assert processor.append(first, sample_rate) == []
    results = processor.append(second, sample_rate)

    audio_results = [result for result in results if result.kind == "audio"]
    assert len(audio_results) == 1
    assert audio_results[0].duration_seconds == 6.0


def test_mic_noise_gate_drops_quiet_chunks_before_gain():
    sample_rate = 16000
    processor = AudioChunkProcessor(
        chunk_duration=1.0,
        input_sample_rate=sample_rate,
        target_sample_rate=sample_rate,
        noise_gate_rms=0.002,
    )
    quiet_noise = np.full(sample_rate, 0.001, dtype=np.float32)

    results = processor.append(quiet_noise, sample_rate)

    assert len(results) == 1
    assert results[0].kind == DROP_NOISE_GATE
    assert results[0].rms < 0.002
    assert processor.silence_run == 1


def test_zero_noise_gate_allows_quiet_audio_to_be_gain_boosted():
    sample_rate = 16000
    processor = AudioChunkProcessor(
        chunk_duration=1.0,
        input_sample_rate=sample_rate,
        target_sample_rate=sample_rate,
        noise_gate_rms=0,
    )
    quiet_audio = np.full(sample_rate, 0.001, dtype=np.float32)

    results = processor.append(quiet_audio, sample_rate)

    assert len(results) == 1
    assert results[0].kind == "audio"
    assert results[0].peak > 0.1
    assert np.max(np.abs(results[0].samples)) > 0.1


def test_digital_silence_reports_digital_silence_not_noise_gate():
    sample_rate = 16000
    processor = AudioChunkProcessor(
        chunk_duration=1.0,
        input_sample_rate=sample_rate,
        target_sample_rate=sample_rate,
        noise_gate_rms=0.002,
    )

    results = processor.append(np.zeros(sample_rate, dtype=np.float32), sample_rate)

    assert len(results) == 1
    assert results[0].kind == DROP_DIGITAL_SILENCE
