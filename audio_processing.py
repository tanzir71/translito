from dataclasses import dataclass

import numpy as np


DROP_DIGITAL_SILENCE = "digital_silence"
DROP_NOISE_GATE = "noise_gate"


@dataclass(frozen=True)
class AudioChunkResult:
    kind: str
    samples: np.ndarray
    sample_rate: int
    peak: float
    rms: float
    source_name: str = ""

    @property
    def duration_seconds(self):
        if self.sample_rate <= 0:
            return 0.0
        return float(len(self.samples)) / float(self.sample_rate)


class AudioChunkProcessor:
    silence_peak_threshold = 0.000001
    silence_rms_threshold = 0.0000005
    quiet_peak_threshold = 0.05
    max_gain = 200.0

    early_emit_min_speech_seconds = 1.5
    early_emit_tail_seconds = 0.7
    early_emit_body_peak_floor = 0.005
    early_emit_drop_ratio = 2.5

    def __init__(
        self,
        chunk_duration=6.0,
        input_sample_rate=48000,
        target_sample_rate=16000,
        noise_gate_rms=0.0,
        source_name="",
    ):
        self.chunk_duration = max(1.0, float(chunk_duration))
        self.input_sample_rate = int(input_sample_rate)
        self.target_sample_rate = int(target_sample_rate)
        self.noise_gate_rms = max(0.0, float(noise_gate_rms))
        self.source_name = source_name
        self.pending = np.asarray([], dtype=np.float32)
        self.silence_run = 0

    @property
    def pending_frame_count(self):
        return int(self.pending.shape[0])

    def append(self, samples, sample_rate):
        mono = self._mono(samples)
        if mono.size == 0:
            return []
        sample_rate = int(sample_rate)
        if sample_rate != self.input_sample_rate:
            self.pending = np.asarray([], dtype=np.float32)
            self.input_sample_rate = sample_rate

        self.pending = np.concatenate([self.pending, mono.astype(np.float32, copy=False)])
        completed = []
        chunk_frames = int(round(self.input_sample_rate * self.chunk_duration))
        while chunk_frames > 0 and self.pending.shape[0] >= chunk_frames:
            native_chunk = self.pending[:chunk_frames]
            self.pending = self.pending[chunk_frames:]
            completed.append(native_chunk)

        if not completed:
            early = self._early_chunk_after_pause()
            if early is not None:
                completed.append(early)

        return [self._finalize_chunk(chunk, self.input_sample_rate) for chunk in completed]

    def flush(self):
        if self.pending.shape[0] < self.input_sample_rate:
            self.pending = np.asarray([], dtype=np.float32)
            return []
        chunk = self.pending
        self.pending = np.asarray([], dtype=np.float32)
        return [self._finalize_chunk(chunk, self.input_sample_rate)]

    def _early_chunk_after_pause(self):
        tail_frames = int(round(self.input_sample_rate * self.early_emit_tail_seconds))
        min_frames = int(round(self.input_sample_rate * self.early_emit_min_speech_seconds))
        if tail_frames <= 0 or self.pending.shape[0] < min_frames + tail_frames:
            return None

        body_count = self.pending.shape[0] - tail_frames
        body = self.pending[:body_count]
        tail = self.pending[body_count:]
        body_peak = float(np.max(np.abs(body))) if body.size else 0.0
        body_rms = _rms(body)
        tail_rms = _rms(tail)
        denominator = max(tail_rms, np.finfo(np.float32).eps)
        if (
            body_peak > self.early_emit_body_peak_floor
            and (body_rms / denominator) > self.early_emit_drop_ratio
        ):
            chunk = self.pending
            self.pending = np.asarray([], dtype=np.float32)
            return chunk
        return None

    def _finalize_chunk(self, native_samples, native_sample_rate):
        samples = resample_audio(native_samples, native_sample_rate, self.target_sample_rate)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        rms = _rms(samples)

        is_digital_silence = (
            peak < self.silence_peak_threshold and rms < self.silence_rms_threshold
        )
        is_below_noise_gate = self.noise_gate_rms > 0 and rms < self.noise_gate_rms
        if is_digital_silence or is_below_noise_gate:
            self.silence_run += 1
            return AudioChunkResult(
                kind=DROP_DIGITAL_SILENCE if is_digital_silence else DROP_NOISE_GATE,
                samples=np.asarray([], dtype=np.float32),
                sample_rate=self.target_sample_rate,
                peak=peak,
                rms=rms,
                source_name=self.source_name,
            )

        self.silence_run = 0
        if peak > 0 and peak < self.quiet_peak_threshold:
            gain = min(self.max_gain, 0.9 / peak)
            samples = (samples * gain).astype(np.float32, copy=False)
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            rms = _rms(samples)

        return AudioChunkResult(
            kind="audio",
            samples=samples.astype(np.float32, copy=False),
            sample_rate=self.target_sample_rate,
            peak=peak,
            rms=rms,
            source_name=self.source_name,
        )

    @staticmethod
    def _mono(samples):
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size == 0:
            return np.asarray([], dtype=np.float32)
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        return audio.reshape(-1).astype(np.float32, copy=False)


def _rms(samples):
    if samples is None or samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32, copy=False)))))


def resample_audio(audio_array, original_sample_rate, target_sample_rate):
    original_sample_rate = int(original_sample_rate)
    target_sample_rate = int(target_sample_rate)
    audio = np.asarray(audio_array, dtype=np.float32)
    if original_sample_rate == target_sample_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size == 0:
        return np.asarray([], dtype=np.float32)
    duration_s = float(audio.shape[0]) / float(original_sample_rate)
    target_len = int(round(duration_s * float(target_sample_rate)))
    if target_len <= 1:
        return np.asarray([], dtype=np.float32)
    original_positions = np.arange(audio.shape[0], dtype=np.float64)
    target_positions = np.linspace(0, audio.shape[0] - 1, num=target_len, dtype=np.float64)
    return np.interp(target_positions, original_positions, audio).astype(np.float32)
