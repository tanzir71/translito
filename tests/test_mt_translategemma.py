import hashlib
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines import mt_translategemma as gemma
from engines.cancellation import GenerationCancelled, generation_scope
from engines.mt_quality import LocalQualityTranslator
from engines.types import MtResult
from tools.eval.runtime import block_network


# This deliberately small fixture exercises llama.cpp's real structured-content
# formatter without copying model templates or downloading licensed weights.
TEMPLATE = "{{ bos_token }}{% for message in messages %}{% if message['role'] == 'user' %}Please translate the following {{ message['content'][0]['source_lang_code'] }} to {{ message['content'][0]['target_lang_code'] }}: {{ message['content'][0]['text'] }}{% else %}{{ message['content'] }}{% endif %}<end_of_turn>{% endfor %}"


class FakeLlama:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.metadata = {"tokenizer.chat_template": TEMPLATE}
        self.calls = []
        self.outputs = []
        self.closed = False

    def tokenize(self, text, **kwargs):
        return list(text)

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"text": self.outputs.pop(0) if self.outputs else "مرحبا"}]}

    def close(self):
        self.closed = True


@pytest.fixture
def translator(tmp_path, monkeypatch):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"fixture, not weights")
    monkeypatch.setitem(gemma.MANIFEST, "template_sha256", hashlib.sha256(TEMPLATE.encode()).hexdigest())
    return gemma.TranslateGemma(path, loader=FakeLlama, ram_check=lambda: True)


def test_gemma_uses_structured_local_template_cpu_context_and_original_token_cap(translator):
    with block_network():
        translator.warmup()
        translator.warmup()
        model = translator.model
        assert len(model.calls) == 1
        model.outputs = ["نشر deployment"]
        result = translator.translate("deployment", "en", "ar", context=[("old", "قديم")],
                                      glossary={"deployment": ""})
    assert result.text == "نشر deployment"
    assert model.options["n_ctx"] == 2048 and model.options["n_gpu_layers"] == 0
    assert model.options["n_threads"] >= 1
    assert model.calls[-1]["max_tokens"] == 3 * len(b"deployment")
    prompt = bytes(model.calls[-1]["prompt"]).decode()
    assert "en to ar-SA" in prompt and "old" in prompt and "قديم" in prompt
    assert "⟦deployment⟧" in prompt and "Keep English" in prompt


def test_gemma_drops_old_context_without_truncating_current_text(translator):
    translator.load()
    translator.model.outputs = ["translated"]
    translator.translate("current", "en", "fa", context=[("older" * 500, "target"), ("recent", "target")], glossary={})
    prompt = bytes(translator.model.calls[-1]["prompt"]).decode()
    assert "older" not in prompt and "recent" in prompt and "current" in prompt
    assert "en to fa" in prompt
    assert gemma.TranslateGemma._message("x", "ur", "ar")["content"][0]["source_lang_code"] == "ur"
    with pytest.raises(gemma.LocalTranslationUnavailable, match="too long"):
        translator.translate("a" * 2100, "en", "ar", context=[], glossary={})


def test_gemma_retries_lost_terms_once_and_preserves_preferred_arabic(translator):
    translator.load()
    translator.model.outputs = ["lost", "still lost"]
    with pytest.raises(gemma.LocalTranslationUnavailable, match="after retry"):
        translator.translate("deployment", "en", "ar", context=[], glossary={"deployment": ""})
    assert len(translator.model.calls) == 2
    assert "Preserve every marked span exactly" in bytes(translator.model.calls[-1]["prompt"]).decode()
    translator.model.outputs = ["⟦نشر⟧"]
    assert translator.translate("DEPLOYMENT", "en", "ar", context=[], glossary={"deployment": "نشر"}).text == "نشر"


def test_gemma_rejects_wrong_template_and_missing_or_low_ram_model(translator, tmp_path):
    invalid = FakeLlama()
    invalid.metadata["tokenizer.chat_template"] = "wrong template"
    translator.loader = lambda **kwargs: invalid
    with pytest.raises(gemma.LocalTranslationUnavailable, match="verified"):
        translator.load()
    assert invalid.closed and translator.model is None
    assert not gemma.TranslateGemma(tmp_path / "missing", ram_check=lambda: True).supports("en", "ar")
    low_ram = gemma.TranslateGemma(translator.path, ram_check=lambda: False)
    with pytest.raises(gemma.LocalTranslationUnavailable, match="8 GB"):
        low_ram.load()


def test_model_download_requires_consent_and_checks_pinned_file(tmp_path, monkeypatch):
    import model_loading
    data = b"test verified artifact"
    manifest = dict(gemma.MANIFEST, filename="fixture.gguf", sha256=hashlib.sha256(data).hexdigest())
    download = Mock(side_effect=lambda *a, **kw: (kw["local_dir"] / manifest["filename"]).write_bytes(data))
    monkeypatch.setattr(model_loading, "_download_repo_with_progress", download)
    with pytest.raises(ValueError, match="accept"):
        gemma.download_model(tmp_path, manifest=manifest)
    download.assert_not_called()
    path = gemma.download_model(tmp_path, accepted_terms=True, manifest=manifest)
    assert path.read_bytes() == data
    assert download.call_args.kwargs["revision"] == manifest["revision"]
    assert download.call_args.kwargs["allow_patterns"] == ["fixture.gguf"]
    with pytest.raises(ValueError, match="checksum"):
        gemma.download_model(tmp_path, accepted_terms=True, manifest=dict(manifest, sha256="invalid"))
    assert path.exists()


def test_cancelled_generation_never_falls_through_to_another_model(translator):
    event = threading.Event()
    translator.load()
    original = translator.model.create_completion

    def cancel(**kwargs):
        event.set()
        assert kwargs["stopping_criteria"]([], [])
        return original(**kwargs)

    translator.model.create_completion = cancel
    opus = Mock()
    engine = LocalQualityTranslator(opus=opus, gemma=translator)
    with generation_scope(event), pytest.raises(GenerationCancelled):
        engine.translate("hello", "en", "ar", context=[], glossary={})
    opus.translate.assert_not_called()


def test_gemma_failure_falls_back_once_with_visible_hint():
    gemma_engine, opus, hint = Mock(), Mock(), Mock()
    gemma_engine.translate.side_effect = gemma.LocalTranslationUnavailable("not ready")
    opus.translate.return_value = MtResult("Hello", "opus-mt")
    engine = LocalQualityTranslator(gemma=gemma_engine, opus=opus, on_hint=hint)
    for _ in range(2):
        assert engine.translate("مرحبا", "ar", "en", context=[], glossary={}).text == "Hello"
    assert hint.call_count == 1 and opus.translate.call_count == 2
