import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
import json
from types import SimpleNamespace

import numpy as np
import pytest

from engines.cost_guard import GateDecision
from engines.paid_streaming import PaidStreamingInterpreter
from engines.settings import EngineSettings, ProviderSettings, credential_signature
from engines.stream_transport import SocketStream
from engines.streaming_protocols import SonioxProtocol
from engines.usage import UsageLedger


@pytest.fixture(autouse=True)
def online_fake_transports(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


@pytest.mark.parametrize("source,target", [("es", "en"), ("en", "ar"), ("fr", "de")])
def test_soniox_is_pair_agnostic_and_does_not_open_until_gated_speech(tmp_path, source, target):
    preference = ProviderSettings(enabled=True, monthly_cap=Decimal(5), account_kind="paid")
    preference = replace(preference, tested_signature=credential_signature("soniox", "fake-key", preference))
    messages, events, headers = [], [], []
    @asynccontextmanager
    async def connector(protocol, auth):
        headers.append(auth)
        replies = asyncio.Queue()
        class Socket:
            async def send(self, value):
                messages.append(value)
                if isinstance(value, bytes):
                    await replies.put(json.dumps({"tokens": [
                        {"text": "Hola.", "is_final": True, "language": source, "end_ms": 800},
                        {"text": "<end>", "is_final": True},
                        {"text": "Hello.", "is_final": True, "translation_status": "translation", "language": target}]}))
                elif value == "":
                    await replies.put(json.dumps({"tokens": [], "finished": True}))
            async def recv(self):
                return await replies.get()
        yield Socket()
    def worker(*args, **kwargs):
        return SocketStream(*args, **kwargs, connector=connector)
    engine = PaidStreamingInterpreter(SimpleNamespace(get=lambda name: "fake-key"), preference,
        settings=EngineSettings(monthly_cap=Decimal(5)), ledger=UsageLedger(tmp_path / "usage.json"),
        inspect_audio=lambda *a: GateDecision(.9, source), worker_factory=worker)
    engine.start((source, target), target, False, lambda k, v: events.append((k, v)))
    assert not headers and not messages
    assert engine.protocol.start()["language_hints"] == [source, target]
    assert engine.push_audio(np.full(16000, .2, np.float32))
    engine.stop()
    engine.worker.thread.join(5)
    assert not engine.worker.thread.is_alive()
    assert headers == [{"Authorization": "Bearer fake-key"}]
    config = json.loads(messages[0])
    assert config["model"] == "stt-rt-v6" and config["translation"]["target_language"] == target
    assert any(k == "input_transcription" and v["text"] == "Hola." for k, v in events)
    assert any(k == "output_transcription" and v["text"] == "Hello." for k, v in events)
    assert not any(k == "fallback" for k, v in events)


def test_source_partial_revision_replaces_text():
    engine = PaidStreamingInterpreter(None, ProviderSettings())
    events = []
    engine.emit = lambda k, v: events.append((k, v))
    protocol = SonioxProtocol(other="es", languages=("es", "en"))
    for text in ("wrong", "Hola"):
        engine._update(protocol.parse({"tokens": [{"text": text, "is_final": False, "language": "es"}]}), 1)
    sources = [v for k, v in events if k == "input_transcription"]
    assert sources[-1]["text"] == "Hola" and sources[-1]["replace"]
