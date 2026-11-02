from email.parser import BytesParser
import io
from types import SimpleNamespace
from unittest.mock import Mock
import threading
import wave

import httpx2
import numpy as np
import pytest

from engines.asr_cloud import AudioQuota
from engines.asr_cohere_api import CohereApiRecognizer
from engines.asr_groq import GroqRecognizer
from engines.cloud_http import CloudHttp
from engines.provider import ProviderQuotaError


@pytest.fixture(autouse=True)
def mock_online(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def multipart(request):
    message = BytesParser().parsebytes(("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode() + request.content)
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.get_payload()}


@pytest.mark.parametrize("cls,provider,model", [(GroqRecognizer, "groq", "whisper-large-v3"),
    (CohereApiRecognizer, "cohere-api", "cohere-transcribe-arabic-07-2026")])
def test_audio_upload_shape_is_mono_16k_wav_with_explicit_language(cls, provider, model):
    def handle(request):
        fields = multipart(request)
        assert fields["model"].decode() == model
        assert fields["language"] == b"en"
        assert request.headers["authorization"] == "Bearer fake-key"
        assert "fake-key" not in str(request.url)
        with wave.open(io.BytesIO(fields["file"]), "rb") as audio:
            assert audio.getframerate() == 16000 and audio.getnchannels() == 1
            assert audio.getsampwidth() == 2 and audio.getnframes() == 32000
        if provider == "groq":
            assert fields["response_format"] == b"verbose_json" and fields["temperature"] == b"0"
            assert len(fields["prompt"]) <= 220
        return httpx2.Response(200, json={"text": "The API works.", "segments": [
            {"text": "The API works.", "avg_logprob": -.2, "no_speech_prob": .01, "compression_ratio": 1.2}]})
    engine = cls(SimpleNamespace(get=lambda _: "fake-key"),
                 http=CloudHttp(httpx2.Client(transport=httpx2.MockTransport(handle))),
                 detector=SimpleNamespace(contains_speech=lambda *a: True), quota=Mock())
    result = engine.transcribe(np.full(96000, .2, dtype=np.float32), 48000, hint_language="en", prompt="API " * 400)
    assert result.text == "The API works." and result.provider == provider
    assert result.language_tag == "en"


@pytest.mark.parametrize("cls", [GroqRecognizer, CohereApiRecognizer])
def test_vad_negative_and_stopped_audio_never_uploads_or_consumes_quota(cls):
    http, quota = Mock(), Mock()
    engine = cls(Mock(), http=http, quota=quota, detector=SimpleNamespace(contains_speech=lambda *a: False))
    assert engine.transcribe(np.ones(32000), 16000, hint_language="ar").text == ""
    assert engine.estimate_usage(np.ones(32000), 16000).requests == 0
    stopped = threading.Event()
    stopped.set()
    from engines.cancellation import GenerationCancelled
    with pytest.raises(GenerationCancelled):
        engine.transcribe(np.ones(32000), 16000, hint_language="ar", stop_event=stopped)
    http.post.assert_not_called()
    quota.take.assert_not_called()


def test_groq_scores_reject_non_speech_and_known_hallucination_before_mt():
    http = SimpleNamespace(post=lambda *a, **kw: {"text": "bad raw", "segments": [
        {"text": "noise", "avg_logprob": -2, "no_speech_prob": .9, "compression_ratio": 1},
        {"text": "Thanks for watching", "avg_logprob": -.2, "no_speech_prob": .01}]})
    engine = GroqRecognizer(SimpleNamespace(get=lambda _: "fake-key"), http=http,
                            detector=SimpleNamespace(contains_speech=lambda *a: True), quota=Mock())
    assert engine.transcribe(np.ones(32000), 16000, hint_language="en").text == ""


def test_token_bucket_allows_at_most_twenty_calls_per_minute_and_rolls_limits():
    now = [0.0]
    quota = AudioQuota(20, clock=lambda: now[0])
    for i in range(20):
        now[0] = 3.0 * i
        quota.take(3)
        with pytest.raises(ProviderQuotaError):
            quota.take(3)
    now[0] = 60
    quota.take(3)
    small = AudioQuota(600, hourly_seconds=10, daily_seconds=15, daily_requests=3, clock=lambda: now[0])
    small.take(10)
    now[0] += 1
    with pytest.raises(ProviderQuotaError):
        small.take(1)
    now[0] += 3600
    small.take(5)
    now[0] += 1
    with pytest.raises(ProviderQuotaError):
        small.take(1)
