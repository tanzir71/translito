from dataclasses import dataclass
import time

import numpy as np


DROP_DIGITAL_SILENCE = "digital_silence"
DROP_NOISE_GATE = "noise_gate"
DROP_NO_SPEECH = "no_speech"


class SpeechActivityDetector:
    """Reject audio without sustained speech before it reaches Whisper."""

    def __init__(self):
        from silero_vad import load_silero_vad

        self.model = load_silero_vad()

    def speech_probability(self, samples, sample_rate):
        import torch
        waveform = torch.from_numpy(np.asarray(samples, dtype=np.float32).copy())
        with torch.inference_mode():
            return float(self.model(waveform, int(sample_rate)).item())

    def contains_speech(self, samples, sample_rate):
        import torch
        from silero_vad import get_speech_timestamps

        sample_rate = int(sample_rate)
        if sample_rate not in (8000, 16000):
            raise ValueError(f"Unsupported voice activity sample rate: {sample_rate}")
        if len(samples) < sample_rate // 5:
            return False

        waveform = torch.from_numpy(np.asarray(samples, dtype=np.float32).copy())
        with torch.inference_mode():
            segments = get_speech_timestamps(
                waveform,
                self.model,
                sampling_rate=sample_rate,
                threshold=0.35,
                min_speech_duration_ms=200,
            )
        return bool(segments)


@dataclass(frozen=True)
class AudioChunkResult:
    kind: str
    samples: np.ndarray
    sample_rate: int
    peak: float
    rms: float
    source_name: str = ""
    captured_at: float | None = None
    endpoint_delay_s: float | None = None
    stream_end_s: float | None = None

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
        speech_detector=None,
        legacy_fixed_window=False,
        on_speech=None,
    ):
        self.chunk_duration = max(1.0, float(chunk_duration))
        self.input_sample_rate = int(input_sample_rate)
        self.target_sample_rate = int(target_sample_rate)
        self.noise_gate_rms = max(0.0, float(noise_gate_rms))
        self.source_name = source_name
        self.speech_detector = speech_detector
        self.legacy_fixed_window = bool(legacy_fixed_window)
        self.on_speech = on_speech
        self.clock = time.monotonic
        self.pending = np.asarray([], dtype=np.float32)
        self.silence_run = 0
        self._frame_buffer = np.asarray([], dtype=np.float32)
        self._pre_roll = np.asarray([], dtype=np.float32)
        self._active = []
        self._active_frames = 0
        self._speech_frames = 0
        self._trailing_frames = 0
        self._short_segment = np.asarray([], dtype=np.float32)
        self._short_speech_frames = 0
        self._inactive_frames = 0

    @property
    def pending_frame_count(self):
        if not self.legacy_fixed_window:
            return self._active_frames + len(self._frame_buffer) + len(self._short_segment)
        return int(self.pending.shape[0])

    def append(self, samples, sample_rate):
        if not self.legacy_fixed_window:
            return self._append_utterances(samples, sample_rate)
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
        if not self.legacy_fixed_window:
            completed = []
            if self._frame_buffer.size:
                size = self.target_sample_rate // 1000 * 32
                padded = np.pad(self._frame_buffer, (0, size - len(self._frame_buffer)))
                self._frame_buffer = np.asarray([], dtype=np.float32)
                completed.extend(self._consume_vad_frame(padded))
            if self._active:
                completed.extend(self._close_segment(force=True))
            if self._short_segment.size:
                completed.append(self._finalize_chunk(self._short_segment, self.target_sample_rate,
                                                      endpoint_delay_s=0.0))
                self._short_segment = np.asarray([], dtype=np.float32)
                self._short_speech_frames = 0
            return completed
        if self.pending.shape[0] < self.input_sample_rate:
            self.pending = np.asarray([], dtype=np.float32)
            return []
        chunk = self.pending
        self.pending = np.asarray([], dtype=np.float32)
        return [self._finalize_chunk(chunk, self.input_sample_rate)]

    def _append_utterances(self, samples, sample_rate):
        mono = self._mono(samples)
        if not mono.size:
            return []
        audio = resample_audio(mono, int(sample_rate), self.target_sample_rate)
        self._frame_buffer = np.concatenate((self._frame_buffer, audio))
        size = self.target_sample_rate // 1000 * 32
        completed = []
        while len(self._frame_buffer) >= size:
            frame = self._frame_buffer[:size]
            self._frame_buffer = self._frame_buffer[size:]
            completed.extend(self._consume_vad_frame(frame))
        return completed

    def _consume_vad_frame(self, frame):
        sr = self.target_sample_rate
        peak, rms = float(np.max(np.abs(frame))), _rms(frame)
        digital = peak < self.silence_peak_threshold and rms < self.silence_rms_threshold
        gated = self.noise_gate_rms > 0 and rms < self.noise_gate_rms
        speech = False
        if not digital and not gated:
            if self.speech_detector is None:
                self.speech_detector = SpeechActivityDetector()
            if hasattr(self.speech_detector, "speech_probability"):
                speech = self.speech_detector.speech_probability(frame, sr) >= 0.35
            else:
                speech = self.speech_detector.contains_speech(frame, sr)
        if speech and callable(self.on_speech):
            self.on_speech(self.clock())
        if not self._active and speech:
            self._active = [self._short_segment, self._pre_roll, frame]
            self._active_frames = sum(len(x) for x in self._active)
            self._short_segment = np.asarray([], dtype=np.float32)
            self._speech_frames = self._short_speech_frames + len(frame)
            self._short_speech_frames = 0
            self._trailing_frames = 0
            self._inactive_frames = 0
        elif self._active:
            self._active.append(frame)
            self._active_frames += len(frame)
            if speech:
                self._speech_frames += len(frame)
                self._trailing_frames = 0
            else:
                self._trailing_frames += len(frame)
        else:
            self._inactive_frames += len(frame)
        self._pre_roll = np.concatenate((self._pre_roll, frame))[-round(sr * 0.3):]
        if self._active and self._active_frames >= round(sr * 15):
            return self._force_close()
        if self._active and self._trailing_frames >= round(sr * 0.6):
            return self._close_segment()
        if not self._active and self._inactive_frames >= round(sr * self.chunk_duration):
            self._inactive_frames = 0
            self.silence_run += 1
            return [AudioChunkResult(
                DROP_DIGITAL_SILENCE if digital else DROP_NOISE_GATE if gated else DROP_NO_SPEECH,
                np.asarray([], dtype=np.float32), sr, peak, rms, self.source_name)]
        return []

    def _close_segment(self, force=False):
        samples = np.concatenate(self._active)
        delay = self._trailing_frames / self.target_sample_rate
        speech_frames = self._speech_frames
        self._active, self._active_frames = [], 0
        self._speech_frames = self._trailing_frames = 0
        self._pre_roll = np.asarray([], dtype=np.float32)
        if not force and speech_frames < self.target_sample_rate:
            self._short_segment = samples
            self._short_speech_frames = speech_frames
            return []
        return [self._finalize_chunk(samples, self.target_sample_rate, endpoint_delay_s=delay)]

    def _force_close(self):
        sr = self.target_sample_rate
        samples = np.concatenate(self._active)
        maximum = round(sr * 15)
        # Prefer a quiet frame in the last half-second, retaining everything
        # after the split as the start of the next segment (no dropped speech).
        size = sr // 1000 * 32
        cuts = list(range(maximum - round(sr * 0.5), maximum + 1, size))
        cut = min(cuts, key=lambda pos: _rms(samples[max(0, pos - size):pos]))
        emitted, remainder = samples[:cut], samples[cut:]
        self._active = [remainder] if remainder.size else []
        self._active_frames = len(remainder)
        self._speech_frames = len(remainder)
        self._trailing_frames = 0
        self._pre_roll = np.asarray([], dtype=np.float32)
        return [self._finalize_chunk(emitted, sr, endpoint_delay_s=0.0)]

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

    def _finalize_chunk(self, native_samples, native_sample_rate, endpoint_delay_s=None):
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

        if self.speech_detector is None:
            self.speech_detector = SpeechActivityDetector()
        if not self.speech_detector.contains_speech(samples, self.target_sample_rate):
            self.silence_run += 1
            return AudioChunkResult(
                kind=DROP_NO_SPEECH,
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
            captured_at=self.clock(),
            endpoint_delay_s=endpoint_delay_s,
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
