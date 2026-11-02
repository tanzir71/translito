import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

from engines.cloud_http import CloudHttp
from engines.mt_azure import AzureTranslator
from engines.mt_google import GoogleTranslator
from engines.provider import AuthenticationError, ProviderBinding, ProviderError, ProviderNetworkError, ProviderQuotaError
from engines.router import TranslatorRouter
from engines.types import MtResult
from engines.usage import Allowance, MonthlyQuota, Rate, UsageLedger


@pytest.fixture(autouse=True)
def online_test_environment(monkeypatch):
    # MockTransport handles every request locally; no cloud credentials or
    # network sockets are used by these contract tests.
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def transport(handler):
    return CloudHttp(httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_azure_rest_contract_preserves_mixed_spans_and_escapes_literal_markup():
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.host == "api.cognitive.microsofttranslator.com"
        assert dict(request.url.params) == {"api-version": "3.0", "from": "ar", "to": "en", "textType": "html"}
        assert request.headers["Ocp-Apim-Subscription-Region"] == "eastus"
        body = json.loads(request.content)
        assert '<span class="notranslate">deployment</span>' in body[0]["Text"]
        assert "&lt;" in body[0]["Text"] and "&gt;" in body[0]["Text"]
        return httpx2.Response(200, json=[{"translations": [{"text": '<div>Finish <span class="notranslate">deployment</span> &lt;literal&gt;.</div>'}]}])
    engine = AzureTranslator(SimpleNamespace(get=lambda _: "fake-key"), region="eastus", http=transport(handle))
    assert engine.translate("هخلص deployment <literal>", "ar", "en", context=[], glossary={}).text == "Finish deployment <literal>."
    assert len(requests) == 1


def test_google_key_stays_in_header_and_html_is_decoded_once(caplog):
    secret = "FAKE-KEY-SENTINEL"
    caplog.set_level(logging.DEBUG)
    def handle(request):
        assert secret not in str(request.url)
        assert request.headers["x-goog-api-key"] == secret
        body = json.loads(request.content)
        assert body["format"] == "html" and body["model"] == "nmt"
        assert '<span translate="no">API</span>' in body["q"][0]
        return httpx2.Response(200, json={"data": {"translations": [{"translatedText": '<div>The API &amp; service.</div>'}]}})
    engine = GoogleTranslator(SimpleNamespace(get=lambda _: secret), http=transport(handle))
    assert engine.translate("نراجع API", "ar", "en", context=[], glossary={}).text == "The API & service."
    assert secret not in caplog.text


@pytest.mark.parametrize("source,text", [("fr", "Vérifiez API maintenant."), ("es", "Revisa API ahora.")])
def test_cloud_latin_source_keeps_ordinary_words_translatable(source, text):
    def handle(request):
        value = json.loads(request.content)[0]["Text"]
        assert value.count("notranslate") == 1
        assert '<span class="notranslate">API</span>' in value
        return httpx2.Response(200, json=[{"translations": [{"text": "Check API now."}]}])
    engine = AzureTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=transport(handle))
    assert engine.translate(text, source, "en", context=[], glossary={"API": ""}).text == "Check API now."


@pytest.mark.parametrize("status,expected", [(401, AuthenticationError), (403, AuthenticationError),
                                          (429, ProviderQuotaError), (456, ProviderQuotaError),
                                          (503, ProviderNetworkError), (400, ProviderError)])
def test_http_errors_never_echo_response_details(status, expected):
    http = transport(lambda request: httpx2.Response(status, json={"message": "PRIVATE KEY OR INPUT"}))
    with pytest.raises(expected) as error:
        http.post("https://example.invalid/translate")
    assert "PRIVATE" not in str(error.value)


def test_redirect_offline_and_bad_json_are_rejected_without_retry(monkeypatch):
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx2.Response(302, headers={"location": "https://other.invalid/"})
    http = transport(redirect)
    with pytest.raises(ProviderError):
        http.post("https://example.invalid/", headers={"Authorization": "fake-secret"})
    assert len(calls) == 1
    monkeypatch.setenv("OFFLINE_ONLY", "1")
    with pytest.raises(ProviderNetworkError):
        http.post("https://example.invalid/")
    assert len(calls) == 1
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    with pytest.raises(ProviderError):
        transport(lambda request: httpx2.Response(200, text="not json")).post("https://example.invalid/")


def test_span_loss_routes_to_local_instead_of_showing_corrupted_terms(tmp_path):
    cloud = AzureTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=transport(
        lambda request: httpx2.Response(200, json=[{"translations": [{"text": "lost the English term"}]}])))
    local = SimpleNamespace(name="local", requires_network=False, supports=lambda *a: True,
                             translate=Mock(return_value=MtResult("Review deployment", "local")))
    router = TranslatorRouter([ProviderBinding(cloud, enabled=True, tested=True, rate=Rate()), ProviderBinding.local(local)],
                                ledger=UsageLedger(tmp_path / "usage.json"))
    assert router.translate("نراجع deployment", "ar", "en", context=[], glossary={}).provider == "local"
    assert router.ledger.snapshot()["providers"]["azure"]["requests"] == 1


def test_preflight_reserves_markup_ceiling_before_network_and_identity_uses_no_quota(tmp_path):
    send = Mock(side_effect=AssertionError("Budget must block this request"))
    cloud = GoogleTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=SimpleNamespace(post=send))
    local = SimpleNamespace(name="local", requires_network=False, supports=lambda *a: True,
                             translate=lambda *a, **kw: MtResult("local", "local"))
    router = TranslatorRouter([ProviderBinding(cloud, enabled=True, tested=True, rate=Rate(per_million_chars=20),
                                                allowance=Allowance(characters=3)), ProviderBinding.local(local)],
                                ledger=UsageLedger(tmp_path / "usage.json"))
    assert router.translate("مرحبا", "ar", "en", context=[], glossary={}).provider == "local"
    assert router.translate("hello", "en", "en", context=[], glossary={}).text == "hello"
    send.assert_not_called()
    assert not router.ledger.path.exists()


def test_simulated_hour_uses_azure_metering_and_costs_zero(tmp_path):
    source = "نراجع المشروع والجدول والتفاصيل قبل الاجتماع. " * 4
    assert 160 <= len(source) <= 210
    calls = []
    def handle(request):
        calls.append(request)
        return httpx2.Response(200, headers={"X-Metered-Usage": str(len(source))},
                               json=[{"translations": [{"text": "Review the project before the meeting."}]}])
    cloud = AzureTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=transport(handle))
    router = TranslatorRouter([ProviderBinding(cloud, enabled=True, tested=True, rate=Rate(),
                                                quota=MonthlyQuota(characters=2_000_000))],
                                ledger=UsageLedger(tmp_path / "usage.json"))
    # 240 utterances of 15 seconds. This checks accounting only, not live quality.
    for _ in range(240):
        assert router.translate(source, "ar", "en", context=[], glossary={}).provider == "azure"
    stats = router.ledger.snapshot()["providers"]["azure"]
    assert 40_000 <= stats["characters"] <= 50_000
    assert stats["characters"] == 240 * len(source) and stats["requests"] == len(calls) == 240
    assert stats["estimated_usd"] == "0"
    data = json.loads(router.ledger.path.read_text())
    first = next(iter(data["reservations"].values()))
    assert first["units"]["characters"] > first["actual_units"]["characters"]
