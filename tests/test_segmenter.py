import numpy as np

from audio_processing import AudioChunkProcessor


SR = 16000


class FrameVad:
    def speech_probability(self, frame, rate):
        return float(np.max(np.abs(frame)) > 0.1)

    def contains_speech(self, samples, rate):
        return np.count_nonzero(samples > 0.1) >= rate * 0.2


def signal(seconds, value):
    return np.full(round(seconds * SR), value, dtype=np.float32)


def replay(processor, audio, flush=True):
    results = []
    for offset in range(0, len(audio), 1600):
        results.extend(processor.append(audio[offset:offset + 1600], SR))
    if flush:
        results.extend(processor.flush())
    return [result for result in results if result.kind == "audio"]


def test_onset_retains_300ms_pre_roll_and_closes_after_600ms_silence():
    processor = AudioChunkProcessor(input_sample_rate=SR, speech_detector=FrameVad())
    audio = np.concatenate([signal(0.5, 0), signal(1.5, 0.2), signal(0.7, 0)])
    results = replay(processor, audio, flush=False)
    assert len(results) == 1
    result = results[0]
    assert 0.6 <= result.endpoint_delay_s < 0.64
    assert 2.3 < result.duration_seconds < 2.5
    assert np.count_nonzero(result.samples[:round(SR * 0.28)]) == 0
    assert np.count_nonzero(result.samples) == round(1.5 * SR)


def test_forced_close_never_exceeds_15s_or_discards_remaining_speech():
    processor = AudioChunkProcessor(input_sample_rate=SR, speech_detector=FrameVad())
    speech = signal(16.5, 0.2)
    results = replay(processor, np.concatenate([speech, signal(0.7, 0)]))
    assert len(results) == 2
    assert max(result.duration_seconds for result in results) <= 15
    assert sum(np.count_nonzero(result.samples) for result in results) == len(speech)


def test_short_segments_merge_into_next_and_flush_if_session_ends():
    processor = AudioChunkProcessor(input_sample_rate=SR, speech_detector=FrameVad())
    audio = np.concatenate([signal(0.5, 0.2), signal(0.7, 0), signal(1.2, 0.3), signal(0.7, 0)])
    results = replay(processor, audio)
    assert len(results) == 1
    assert np.count_nonzero(results[0].samples) == round(SR * 1.7)
    short = AudioChunkProcessor(input_sample_rate=SR, speech_detector=FrameVad())
    assert len(replay(short, np.concatenate([signal(0.5, 0.2), signal(0.7, 0)]))) == 1


def test_steady_noise_never_becomes_audio_when_vad_rejects_it():
    class NoSpeech:
        def speech_probability(self, frame, rate):
            return 0

        def contains_speech(self, samples, rate):
            raise AssertionError("VAD-negative stream should not be decoded/finalized as speech")

    processor = AudioChunkProcessor(input_sample_rate=SR, speech_detector=NoSpeech())
    assert replay(processor, signal(30, 0.02)) == []
    assert processor.pending_frame_count == 0


def test_gate_precedes_vad_and_gain():
    class FailIfCalled:
        def speech_probability(self, frame, rate):
            raise AssertionError("Noise gate should reject before VAD")

    processor = AudioChunkProcessor(input_sample_rate=SR, noise_gate_rms=0.002,
                                    speech_detector=FailIfCalled())
    assert replay(processor, signal(3, 0.001)) == []
