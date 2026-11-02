"""VAD-gated WAV uploads and shared local quota state for cloud ASR."""
from collections import deque
from functools import lru_cache
import io
import math
import threading
import time
import wave

import numpy as np

from audio_processing import SpeechActivityDetector, resample_audio
from engines.cancellation import check_cancelled
from engines.lid import language_tag, latin_ratio
from engines.postprocess import postprocess
from engines.provider import ProviderError, ProviderThrottleError
from engines.types import AsrResult
from engines.usage import Units


class AudioQuota:
    """A conservative one-token bucket plus rolling hour/day ceilings."""
    def __init__(self, rpm, *, hourly_seconds=None, daily_seconds=None, daily_requests=None, clock=time.monotonic):
        self.interval = 60 / rpm
        self.hourly_seconds, self.daily_seconds = hourly_seconds, daily_seconds
        self.daily_requests = daily_requests
        self.clock = clock
        self.next_token_at = 0
        self.history = deque()
        self.lock = threading.Lock()

    def take(self, seconds):
        with self.lock:
            now = self.clock()
            while self.history and self.history[0][0] <= now - 86400:
                self.history.popleft()
            hour = sum(value for timestamp, value in self.history if timestamp > now - 3600)
            day = sum(value for _, value in self.history)
            if (now < self.next_token_at or self.hourly_seconds is not None and hour + seconds > self.hourly_seconds
                    or self.daily_seconds is not None and day + seconds > self.daily_seconds
                    or self.daily_requests is not None and len(self.history) >= self.daily_requests):
                raise ProviderThrottleError()
            self.next_token_at = now + self.interval
            self.history.append((now, seconds))


@lru_cache(maxsize=8)
def shared_quota(provider):
    if provider == "cohere-api":
        return AudioQuota(5)
    if provider == "groq":
        return AudioQuota(20, hourly_seconds=7200, daily_seconds=28800, daily_requests=2000)
    raise ValueError("Unknown ASR quota")


def prepared_audio(audio, sample_rate, detector):
    check_cancelled()
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim != 1 or int(sample_rate) <= 0 or not np.isfinite(samples).all():
        raise ProviderError()
    if len(samples) / sample_rate > 15.05:
        raise ProviderError()
    samples = resample_audio(samples, sample_rate, 16000)
    if not samples.size or float(np.max(np.abs(samples))) < .000001 or not detector.contains_speech(samples, 16000):
        return None
    check_cancelled()
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        return buffer.getvalue()


def number(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def result(text, language, duration, provider, *, avg_logprob=None, no_speech_prob=None):
    if not isinstance(text, str):
        raise ProviderError()
    cleaned = postprocess(text).text
    return AsrResult(cleaned, language, None, language_tag(cleaned, acoustic_language=language),
                     latin_ratio(cleaned), avg_logprob, no_speech_prob, duration, provider)


class CloudRecognizer:
    requires_network = True
    languages = None

    def __init__(self, credentials, *, http=None, detector=None, quota=None):
        from engines.cloud_http import CloudHttp
        self.credentials = credentials
        self.http = http or CloudHttp()
        self.detector = detector
        self.quota = quota or shared_quota(self.name)

    def _audio(self, audio, rate):
        if self.detector is None:
            self.detector = SpeechActivityDetector()
        return prepared_audio(audio, rate, self.detector)

    def estimate_usage(self, audio, sample_rate, **kwargs):
        accepted = self._audio(audio, sample_rate) is not None
        return Units(audio_seconds=len(audio) / sample_rate if accepted else 0, requests=int(accepted))
