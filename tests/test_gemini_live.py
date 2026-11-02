import asyncio
from dataclasses import replace
import json
import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from google.genai import types

from engines.interp_gemini_live import GeminiLiveInterpreter, MODEL, _client, connect_config
from engines.provider import AuthenticationError, ProviderNetworkError
from engines.settings import ProviderSettings, credential_signature
from engines.usage import UsageLedger


def authorized():
    preference = ProviderSettings(enabled=True, account_kind="free", training_consent=True)
    return replace(preference, tested_signature=credential_signature("gemini-live", "fake-key", preference))


class FakeSession:
    def __init__(self, responses=()):
        self.queue = asyncio.Queue()
        for response in responses:
            self.queue.put_nowait(response)
        self.uploaded = []
        self.sent = threading.Event()

    async def send_realtime_input(self, **kwargs):
        self.uploaded.append(kwargs["audio"])
        self.sent.set()

    async def receive(self):
        value = await self.queue.get()
        if isinstance(value, Exception):
            raise value
        yield value


class FakeClients:
    def __init__(self, sessions):
        self.sessions, self.configs, self.closed = list(sessions), [], []

    def __call__(self, key):
        assert key == "fake-key"
        session = self.sessions.pop(0)
        owner = self
        class Connection:
            async def __aenter__(self):
                if isinstance(session, Exception):
                    raise session
                return session
            async def __aexit__(self, *a):
                pass
        def connect(**kwargs):
            owner.configs.append(kwargs)
            return Connection()
        async def close():
            owner.closed.append(session)
        return SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=close))


@pytest.fixture(autouse=True)
def online(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def worker(tmp_path, sessions, preference=None):
    factory = FakeClients(sessions)
    value = GeminiLiveInterpreter(SimpleNamespace(get=lambda _: "fake-key"), preference or authorized(),
                                    ledger=UsageLedger(tmp_path / "usage.json"), client_factory=factory, reconnect_delay=.01)
    return value, factory


def test_typed_config_is_one_way_audio_with_no_target_language_echo():
    config = connect_config("ar", "opaque-resume-handle")
    assert config.translation_config.target_language_code == "ar"
    assert config.translation_config.echo_target_language is False
    assert config.input_audio_transcription is not None and config.output_audio_transcription is not None
    assert config.response_modalities == [types.Modality.AUDIO]
    assert config.session_resumption.handle == "opaque-resume-handle"
    assert connect_config("en", resume=False).session_resumption is None


def test_installed_sdk_wire_schema_and_header_auth_with_sockets_blocked(monkeypatch, caplog):
    import google.genai.live
    from tools.eval.runtime import block_network
    sent, connections = [], []
    caplog.set_level(logging.DEBUG)
    class WebSocket:
        replies = [json.dumps({"setupComplete": {}}), json.dumps({"serverContent": {
            "inputTranscription": {"text": "مرحبا", "languageCode": "ar"}, "turnComplete": True}})]
        async def send(self, value):
            sent.append(json.loads(value))
        async def recv(self, **kwargs):
            return self.replies.pop(0)
    class Connection:
        async def __aenter__(self):
            return WebSocket()
        async def __aexit__(self, *args):
            pass
    def connect(uri, additional_headers, **kwargs):
        logging.getLogger("websockets.client").debug("headers %s", additional_headers)
        connections.append((uri, additional_headers))
        return Connection()
    monkeypatch.setattr(google.genai.live, "ws_connect", connect)
    async def run():
        client = _client("FAKE-KEY-NEVER-IN-LOGS")
        try:
            async with client.aio.live.connect(model=MODEL, config=connect_config("en")) as session:
                await session.send_realtime_input(audio=types.Blob(data=b"\x00\x00" * 1600, mime_type="audio/pcm;rate=16000"))
                responses = [response async for response in session.receive()]
                assert responses[0].server_content.input_transcription.text == "مرحبا"
        finally:
            await client.aio.aclose()
            client.close()
    async def blocked_run():
        # Windows creates a local socket pair while initializing its event
        # loop. Block external operations after that loop already exists.
        with block_network():
            await run()
    asyncio.run(blocked_run())
    uri, headers = connections[0]
    assert "FAKE-KEY" not in uri and headers["x-goog-api-key"] == "FAKE-KEY-NEVER-IN-LOGS"
    setup = sent[0]["setup"]
    assert setup["model"] == "models/" + MODEL
    config = setup["generationConfig"]
    assert config["translationConfig"] == {"targetLanguageCode": "en", "echoTargetLanguage": False}
    assert config["responseModalities"] == ["AUDIO"]
    # This pinned SDK uses the accepted protobuf field name for the envelope.
    assert sent[1]["realtime_input"]["audio"]["mime_type"] == "audio/pcm;rate=16000"
    assert "FAKE-KEY" not in caplog.text and "مرحبا" not in caplog.text


@pytest.mark.parametrize("change", [{"enabled": False}, {"tested_signature": ""}, {"training_consent": False},
                                    {"account_kind": "paid"}, {"monthly_cap": 1}])
def test_account_test_and_privacy_gates_run_before_client_or_usage(tmp_path, change):
    instance, factory = worker(tmp_path, [], replace(authorized(), **change))
    with pytest.raises(AuthenticationError):
        instance.start(("en", "ar"), "en", False, Mock())
    assert factory.configs == [] and not instance.ledger.path.exists()


def test_offline_and_two_way_requests_are_refused_without_opening_client(tmp_path, monkeypatch):
    instance, factory = worker(tmp_path, [])
    monkeypatch.setenv("OFFLINE_ONLY", "1")
    with pytest.raises(ProviderNetworkError):
        instance.start(("en", "ar"), "en", False, Mock())
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    with pytest.raises(ValueError, match="one-way"):
        instance.start(("en", "ar"), "en", True, Mock())
    assert factory.configs == []


def test_fake_live_session_uploads_100ms_pcm_and_publishes_text_and_24k_audio(tmp_path):
    session = FakeSession([types.LiveServerMessage(server_content=types.LiveServerContent(
        input_transcription=types.Transcription(text="مرحبا", language_code="ar", finished=True),
        output_transcription=types.Transcription(text="Hello", language_code="en", finished=True),
        model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(
            data=b"\x01\x00" * 2400, mime_type="audio/pcm;rate=24000"))])))])
    instance, factory = worker(tmp_path, [session])
    events, audio_received = [], threading.Event()
    def emit(kind, payload):
        events.append((kind, payload))
        if kind == "audio":
            audio_received.set()
    instance.start(("en", "ar"), "en", False, emit)
    try:
        assert instance.push_audio(np.ones(800, np.float32) * .25)
        assert instance.push_audio(np.ones(800, np.float32) * .25)
        assert session.sent.wait(2) and audio_received.wait(2)
        assert len(session.uploaded) == 1
        assert len(session.uploaded[0].data) == 3200
        assert session.uploaded[0].mime_type == "audio/pcm;rate=16000"
        assert next(payload for kind, payload in events if kind == "audio")["rate"] == 24000
        assert next(payload for kind, payload in events if kind == "input_transcription")["language"] == "ar"
        assert factory.configs[0]["model"] == MODEL
    finally:
        instance.stop()
    assert not instance._thread.is_alive() and factory.closed == [session]
    assert instance.frames.empty() and instance._pending is None and not instance._tail.size
    assert not instance.push_audio(np.zeros(1600, np.float32))
    stats = instance.ledger.snapshot()["providers"]["gemini-live"]
    assert stats["audio_seconds"] == pytest.approx(.1) and stats["requests"] == 1
    assert stats["estimated_usd"] == "0"
    assert "مرحبا" not in instance.ledger.path.read_text() and "fake-key" not in instance.ledger.path.read_text()


def test_goaway_reconnect_uses_resume_handle_and_stop_cancels_blocked_receive(tmp_path):
    first = FakeSession([
        types.LiveServerMessage(session_resumption_update=types.LiveServerSessionResumptionUpdate(
            resumable=True, new_handle="opaque-handle")),
        types.LiveServerMessage(go_away=types.LiveServerGoAway(time_left="10s"))])
    second = FakeSession()
    instance, factory = worker(tmp_path, [first, second])
    connected_twice = threading.Event()
    connections = []
    def emit(kind, payload):
        if kind == "connected":
            connections.append(True)
            if len(connections) == 2:
                connected_twice.set()
    instance.start(("en", "ar"), "en", False, emit)
    try:
        assert connected_twice.wait(2)
        assert factory.configs[1]["config"].session_resumption.handle == "opaque-handle"
    finally:
        instance.stop()
    assert not instance._thread.is_alive() and len(factory.closed) == 2


def test_repeated_failures_trigger_free_fallback_with_no_sdk_details(tmp_path):
    instance, factory = worker(tmp_path, [RuntimeError("SECRET-KEY PRIVATE-TEXT")] * 3)
    fallback = threading.Event()
    events = []
    def emit(kind, payload):
        events.append((kind, payload))
        if kind == "fallback":
            fallback.set()
    instance.start(("en", "ar"), "en", False, emit)
    try:
        assert fallback.wait(2)
    finally:
        instance.stop()
    assert instance.failed and len(factory.configs) == 3
    assert "SECRET" not in json.dumps(events) and "PRIVATE" not in json.dumps(events)
    assert not instance.ledger.path.exists()


def test_preview_retries_without_resumption_when_server_rejects_that_capability(tmp_path):
    error = RuntimeError("PRIVATE SDK details")
    error.code = 400
    session = FakeSession()
    instance, factory = worker(tmp_path, [error, session])
    connected = threading.Event()
    instance.start(("en", "ar"), "en", False, lambda kind, data: connected.set() if kind == "connected" else None)
    try:
        assert connected.wait(2)
        assert factory.configs[0]["config"].session_resumption is not None
        assert factory.configs[1]["config"].session_resumption is None
    finally:
        instance.stop()
    assert not instance._thread.is_alive()
