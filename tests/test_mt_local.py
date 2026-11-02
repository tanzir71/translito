from unittest.mock import Mock

import pytest

from engines.mt_local import LocalOpusPipeline, OpusTranslator, UnsupportedPairError, resolve_local_mt
from tools.eval.runtime import block_network


def test_local_pair_resolver_uses_direct_then_english_pivot():
    direct = "Helsinki-NLP/opus-mt-ar-fr"
    assert resolve_local_mt("ar", "fr", repo_exists=lambda repo: repo == direct).repos == (direct,)
    pivot = ("Helsinki-NLP/opus-mt-ar-en", "Helsinki-NLP/opus-mt-en-fr")
    assert resolve_local_mt("ar", "fr", repo_exists=lambda repo: repo in pivot).repos == pivot
    with pytest.raises(UnsupportedPairError, match="needs TranslateGemma or a cloud translator"):
        resolve_local_mt("ar", "fa", repo_exists=lambda repo: False)
    assert resolve_local_mt("en", "en").repos == ()


def test_offline_capability_resolution_makes_no_socket_calls():
    with block_network():
        assert resolve_local_mt("ar", "en").repos == ("Helsinki-NLP/opus-mt-ar-en",)
        with pytest.raises(UnsupportedPairError):
            resolve_local_mt("en", "zz")


def test_direct_model_adapter_passes_offline_flag_and_generation_options(monkeypatch):
    import torch
    import transformers
    load_tokenizer, load_model = Mock(), Mock()
    tokenizer = Mock()
    tokenizer.return_value = {"input_ids": torch.tensor([[1, 2, 3]])}
    tokenizer.batch_decode.return_value = [" Hello "]
    load_tokenizer.return_value = tokenizer
    model = Mock()
    model.to.return_value = model
    model.eval.return_value = model
    model.generate.return_value = torch.tensor([[4, 5]])
    load_model.return_value = model
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", load_tokenizer)
    monkeypatch.setattr(transformers.AutoModelForSeq2SeqLM, "from_pretrained", load_model)
    pipeline = LocalOpusPipeline("Helsinki-NLP/opus-mt-ar-en", offline_only=True)
    assert pipeline("مرحبا", num_beams=4, max_new_tokens=32, truncation=True) == [
        {"translation_text": "Hello"}]
    assert load_model.call_args.kwargs == {"local_files_only": True, "token": False}
    assert load_tokenizer.call_args.kwargs == {"local_files_only": True, "token": False}
    assert model.generate.call_args.kwargs["num_beams"] == 4
    assert model.generate.call_args.kwargs["max_new_tokens"] == 32
    assert "truncation" not in model.generate.call_args.kwargs


def test_opus_adapter_protects_terms_and_keeps_models_warm():
    loader = Mock()
    pipeline = Mock()
    pipeline.tokenizer = None
    pipeline.side_effect = lambda text, **kw: [{"translation_text": text}]
    loader.return_value = pipeline
    translator = OpusTranslator(loader=loader)
    for _ in range(2):
        translated = translator.translate("هخلص ال deployment بعد ال meeting", "ar", "en",
                                         context=[], glossary={})
        assert "deployment" in translated.text and "meeting" in translated.text
    assert loader.call_count == 1
    assert pipeline.call_args.kwargs["num_beams"] == 4
    assert "deployment" not in pipeline.call_args.args[0]


def test_same_language_never_loads_an_mt_model():
    loader = Mock(side_effect=AssertionError("No model should load"))
    translator = OpusTranslator(loader=loader)
    assert translator.translate("Hello", "en", "en", context=[], glossary={}).text == "Hello"
    loader.assert_not_called()
