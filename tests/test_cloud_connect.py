from dataclasses import replace
from decimal import Decimal
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from engines.cloud_connect import CloudConnector, ConnectionError, check_key
from engines.engine_status import engine_status
from engines.settings import EngineSettings, ProviderSettings, load_engine_settings, save_engine_settings
from engines.registry import configured_live_interpreter


@pytest.fixture
def connection(tmp_path):
    keys = {}
    credentials = SimpleNamespace(get=keys.get, save=lambda p,k: keys.update({p:k}), delete=lambda p: keys.pop(p, None))
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET" and not request.content
        return httpx.Response(200, json={})
    path = tmp_path / "config.ini"
    save_engine_settings(EngineSettings(engine_choice="cloud", profile="custom"), path)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    yield CloudConnector(path, credentials, client=client), keys, calls
    client.close()


def test_connect_is_free_at_zero_budget_and_remove_clears_key_and_signature(connection):
    controller, keys, calls = connection
    assert controller.connect("soniox", "fake-key-7f3a") == "7f3a"
    assert keys["soniox"] == "fake-key-7f3a"
    assert calls[0].url.path == "/v1/models"
    assert calls[0].headers["Authorization"] == "Bearer fake-key-7f3a"
    assert controller.status("soniox")[2]
    text = controller.path.read_text()
    assert "fake-key" not in text and "7f3a" not in text
    settings = load_engine_settings(controller.path)
    assert engine_status(settings, ("ar", "en")).text == "On this PC · needs a monthly budget"
    credentials = Mock()
    assert configured_live_interpreter(settings, credentials=credentials, pair=("ar", "en")) is None
    credentials.get.assert_not_called()
    controller.remove("soniox")
    assert not keys and not load_engine_settings(controller.path).provider("soniox").tested_signature


def test_shared_five_dollar_budget_builds_soniox_without_separate_limit(connection):
    controller, keys, _ = connection
    controller.connect("soniox", "fake-key")
    from settings_store import SettingsStore
    SettingsStore(controller.path).update({("ENGINES", "monthly_cap_usd"): "5.00"}, sync=True)
    settings = load_engine_settings(controller.path)
    assert settings.provider("soniox").monthly_cap == 5
    assert settings.provider("soniox").inherit_monthly_cap
    assert engine_status(settings, ("ar", "en")).text == "Soniox"
    engine = configured_live_interpreter(settings, credentials=controller.credentials, pair=("ar", "en"))
    assert engine.name == "soniox"
    assert engine.guard is None  # construction sends nothing


@pytest.mark.parametrize("code,message", [(401, "That key was rejected by Soniox."), (403, "That key was rejected by Soniox."),
    (429, "Soniox returned an error (code 429). Try again later."), (500, "Soniox returned an error (code 500). Try again later.")])
def test_rejected_keys_and_server_errors_are_readable(code, message):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(code))) as client:
        with pytest.raises(ConnectionError, match=__import__("re").escape(message)):
            check_key("soniox", "secret", client=client)


def test_network_error_never_echoes_a_key():
    def fail(request):
        raise httpx.ConnectError("secret signed URL", request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ConnectionError) as caught:
            check_key("soniox", "secret", client=client)
    assert str(caught.value) == "Couldn't reach Soniox. Check your connection."


@pytest.mark.parametrize("provider,path,header", [("elevenlabs", "/v1/user", "xi-api-key"),
    ("speechmatics", "/v2/jobs/", "authorization"), ("gemini", "/v1beta/models", "x-goog-api-key"),
    ("groq", "/openai/v1/models", "authorization"), ("cohere-api", "/v1/models", "authorization"),
    ("deepl", "/v2/usage", "authorization"), ("google", "/language/translate/v2/languages", None)])
def test_metadata_endpoint_contracts(provider, path, header):
    seen = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200))[1])) as client:
        check_key(provider, "test-key", client=client)
    assert seen[0].method == "GET" and seen[0].url.path == path and not seen[0].content
    if header:
        assert "test-key" in seen[0].headers[header]


def test_remove_during_check_does_not_restore_the_key(connection):
    controller, keys, _ = connection
    began, finish = threading.Event(), threading.Event()
    controller.checker = lambda *a, **kw: (began.set(), finish.wait(2))
    errors = []
    def connect():
        try:
            controller.connect("soniox", "do-not-restore")
        except ConnectionError as error:
            errors.append(str(error))
    worker = threading.Thread(target=connect)
    worker.start()
    assert began.wait(1)
    controller.remove("soniox")
    finish.set()
    worker.join(2)
    assert errors and not keys
