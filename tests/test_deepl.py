import json
import sqlite3
from types import SimpleNamespace

import httpx2
import pytest

from engines.cloud_http import CloudHttp
from engines.mt_deepl import DeepLTranslator
from engines.provider import AuthenticationError, ProviderQuotaError


@pytest.fixture(autouse=True)
def mock_online(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def test_free_host_xml_context_and_glossary_is_created_once_and_retained(tmp_path):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.host == "api-free.deepl.com"
        assert request.headers["authorization"] == "DeepL-Auth-Key fake:fx"
        if request.url.path == "/v3/languages":
            assert request.url.params["resource"] == "glossary"
            return httpx2.Response(200, json=[{"lang": "ar", "usable_as_source": True}, {"lang": "en", "usable_as_target": True}])
        body = json.loads(request.content)
        if request.url.path == "/v3/glossaries":
            assert body["dictionaries"][0]["entries"] == "deployment\tdeployment"
            return httpx2.Response(201, json={"glossary_id": "id-123"})
        assert body["glossary_id"] == "id-123" and body["ignore_tags"] == ["x"]
        assert body["tag_handling"] == "xml" and body["tag_handling_version"] == "v2"
        assert "<x>deployment</x>" in body["text"][0]
        assert body["context"] == "قبل\nBefore"
        return httpx2.Response(200, json={"translations": [{"text": "<text>Review <x>deployment</x>.</text>"}]})
    cache = tmp_path / "glossaries.sqlite3"
    engine = DeepLTranslator(SimpleNamespace(get=lambda _: "fake:fx"),
        http=CloudHttp(httpx2.Client(transport=httpx2.MockTransport(handle))), cache_path=cache)
    for _ in range(2):
        assert engine.translate("راجع deployment", "ar", "en", context=[("قبل", "Before")],
                                 glossary={"deployment": ""}).text == "Review deployment."
    assert sum(r.url.path == "/v3/glossaries" for r in requests) == 1
    with sqlite3.connect(cache) as db:
        assert db.execute("SELECT count(*) FROM glossary_records").fetchone()[0] == 1
        assert "fake:fx" not in repr(db.execute("SELECT * FROM glossary_records").fetchall())


def test_deepl_unsupported_glossary_uses_protected_text_and_paid_key_never_sends(tmp_path):
    requests = []
    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx2.Response(200, json=[])
        assert "glossary_id" not in json.loads(request.content)
        return httpx2.Response(200, json={"translations": [{"text": "API works."}]})
    http = CloudHttp(httpx2.Client(transport=httpx2.MockTransport(handle)))
    engine = DeepLTranslator(SimpleNamespace(get=lambda _: "fake:fx"), http=http, cache_path=tmp_path / "cache.sqlite3")
    assert engine.translate("راجع API", "ar", "en", context=[], glossary={"API": ""}).text == "API works."
    assert not engine.cache_path.exists()
    engine.credentials = SimpleNamespace(get=lambda _: "fake-paid")
    with pytest.raises(AuthenticationError):
        engine.translate("مرحبا", "ar", "en", context=[], glossary={})
    assert len(requests) == 2


def test_deepl_456_is_quota_and_usage_metadata_is_typed(tmp_path):
    engine = DeepLTranslator(SimpleNamespace(get=lambda _: "fake:fx"), cache_path=tmp_path / "cache.sqlite3",
        http=CloudHttp(httpx2.Client(transport=httpx2.MockTransport(lambda request: httpx2.Response(456, json={"message": "private"})))))
    with pytest.raises(ProviderQuotaError):
        engine.translate("مرحبا", "ar", "en", context=[], glossary={})
    engine.http = SimpleNamespace(get=lambda *a, **kw: {"character_count": 123, "character_limit": 500000})
    assert engine.account_usage() == {"used": 123, "limit": 500000}
