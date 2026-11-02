import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest

from engines.cloud_http import CloudHttp
from engines.mt_gemini import GeminiTranslator, build
from engines.provider import ProviderError
from engines.settings import ProviderSettings


@pytest.fixture(autouse=True)
def mock_online(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def test_gemini_batches_existing_sentences_and_uses_current_rest_json_schema():
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers["x-goog-api-key"] == "fake-key"
        assert "fake-key" not in str(request.url)
        payload = json.loads(request.content)
        data = json.loads(payload["contents"][0]["parts"][0]["text"])
        assert len(data["sentences"]) == 3
        assert data["context"] == [["قبل", "Before"]]
        assert data["glossary"] == {"API": ""}
        schema = payload["generationConfig"]["responseFormat"]["text"]
        assert schema["mimeType"] == "APPLICATION_JSON"
        assert schema["schema"]["properties"]["translations"]["minItems"] == 3
        return httpx2.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": json.dumps({"translations": ["Review ⟦API⟧.", "Good morning.", "Start now."]})}]}}],
            "usageMetadata": {"promptTokenCount": 90, "totalTokenCount": 120}})
    engine = GeminiTranslator(SimpleNamespace(get=lambda _: "fake-key"),
        http=CloudHttp(httpx2.Client(transport=httpx2.MockTransport(handle))))
    output = engine.translate("نراجع API. صباح الخير. نبدأ الآن.", "ar", "en", context=[("قبل", "Before")], glossary={"API": ""})
    assert output.text == "Review API. Good morning. Start now."
    assert len(requests) == 1 and output.usage.requests == 1
    assert output.usage.input_tokens == 90 and output.usage.output_tokens == 30
    estimate = engine.estimate_usage("نراجع API. صباح الخير. نبدأ الآن.", "ar", "en", context=[("قبل", "Before")], glossary={"API": ""})
    assert estimate.requests == 2 and estimate.input_tokens > output.usage.input_tokens


def test_gemini_retries_span_loss_once_and_keeps_total_usage_for_both_attempts():
    attempts = []
    def post(*args, **kwargs):
        attempts.append(kwargs["json"])
        text = "lost" if len(attempts) == 1 else "Review ⟦deployment⟧."
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"translations": [text]})}]}}],
                "usageMetadata": {"promptTokenCount": 20, "totalTokenCount": 30}}
    engine = GeminiTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=SimpleNamespace(post=post))
    result = engine.translate("راجع deployment", "ar", "en", context=[], glossary={})
    assert result.text == "Review deployment." and result.usage.requests == 2
    assert result.usage.input_tokens == 40 and result.usage.output_tokens == 20
    assert "every occurrence" in attempts[1]["systemInstruction"]["parts"][0]["text"]
    engine.http = SimpleNamespace(post=lambda *a, **kw: {"candidates": [{"content": {"parts": [{"text": "not JSON"}]}}]})
    with pytest.raises(ProviderError):
        engine.translate("راجع deployment", "ar", "en", context=[], glossary={})


def test_training_consent_and_free_account_are_required_for_a_priced_binding():
    credentials = Mock()
    assert build(ProviderSettings(account_kind="free"), credentials).rate is None
    assert build(ProviderSettings(account_kind="paid", training_consent=True), credentials).rate is None
    assert build(ProviderSettings(account_kind="free", training_consent=True), credentials).rate is not None


def test_latin_source_and_identity_do_not_mask_whole_sentence_or_call_unnecessarily():
    seen = []
    def post(*args, **kwargs):
        data = json.loads(kwargs["json"]["contents"][0]["parts"][0]["text"])
        seen.extend(data["sentences"])
        return {"candidates": [{"content": {"parts": [{"text": '{"translations":["Check API now."]}'}]}}]}
    engine = GeminiTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=SimpleNamespace(post=post))
    assert engine.translate("Vérifiez API maintenant.", "fr", "en", context=[], glossary={"API": ""}).text == "Check API now."
    assert seen == ["Vérifiez ⟦API⟧ maintenant."]
    assert engine.translate("Hello", "en", "en", context=[], glossary={}).text == "Hello"
    assert len(seen) == 1


def test_router_settles_actual_usage_and_preserves_two_attempt_reservation(tmp_path):
    import json
    from engines.provider import ProviderBinding
    from engines.router import TranslatorRouter
    from engines.usage import LOCAL_RATE, UsageLedger
    engine = GeminiTranslator(SimpleNamespace(get=lambda _: "fake-key"), http=SimpleNamespace(post=lambda *a, **kw:
        {"candidates": [{"content": {"parts": [{"text": '{"translations":["Hello."]}'}]}}],
         "usageMetadata": {"promptTokenCount": 30, "totalTokenCount": 35}}))
    ledger = UsageLedger(tmp_path / "usage.json")
    router = TranslatorRouter([ProviderBinding(engine, enabled=True, tested=True, rate=LOCAL_RATE)], ledger=ledger)
    assert router.translate("مرحبا.", "ar", "en", context=[], glossary={}).text == "Hello."
    stats = ledger.snapshot()["providers"]["gemini"]
    assert stats["requests"] == 1 and stats["input_tokens"] == 30 and stats["output_tokens"] == 5
    record = next(iter(json.loads(ledger.path.read_text())["reservations"].values()))
    assert record["units"]["requests"] == 2 and record["actual_units"]["requests"] == 1
