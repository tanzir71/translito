import json
from unittest.mock import Mock

import pytest

from engines.asr_codeswitch import (CODESWITCH_REPO, TOKENIZER_REPO, load_cached_codeswitch,
                                    prepare_codeswitch_model, prepared_codeswitch_directory, validate_tokenizer)
from tools.eval.runtime import block_network


def model_files(folder):
    (folder / "model.bin").write_bytes(b"weights")
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / "vocabulary.json").write_text(json.dumps(["word", "<special>"]), encoding="utf-8")


def tokenizer_file(folder, special=1):
    (folder / "tokenizer.json").write_text(json.dumps({
        "model": {"vocab": {"word": 0}}, "added_tokens": [{"id": special, "content": "<special>"}]
    }), encoding="utf-8")


def test_download_uses_inference_files_and_matching_source_tokenizer(tmp_path, monkeypatch):
    import model_loading
    import huggingface_hub
    calls = []

    def download(repo, label, offset, span, on_event, **kwargs):
        calls.append((repo, kwargs))
        assert kwargs["allow_patterns"] == ["model.bin", "config.json", "vocabulary.json"]
        model_files(tmp_path)

    def download_tokenizer(repo, filename, **kwargs):
        assert repo == TOKENIZER_REPO and filename == "tokenizer.json"
        assert kwargs["token"] is False
        tokenizer_file(tmp_path)

    monkeypatch.setattr(model_loading, "_download_repo_with_progress", download)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download_tokenizer)
    with block_network():
        assert prepare_codeswitch_model(tmp_path) == str(tmp_path)
    assert calls[0][0] == CODESWITCH_REPO
    assert prepared_codeswitch_directory(tmp_path) == str(tmp_path)


def test_incomplete_or_mismatched_tokenizer_never_opens_a_model(tmp_path):
    model_files(tmp_path)
    assert prepared_codeswitch_directory(tmp_path) is None
    tokenizer_file(tmp_path, special=7)
    with pytest.raises(ValueError, match="does not match"):
        validate_tokenizer(tmp_path)
    assert (tmp_path / "tokenizer.json").is_file()


def test_cached_load_is_explicitly_offline_and_has_local_tokenizer(tmp_path, monkeypatch):
    import faster_whisper
    model_files(tmp_path)
    tokenizer_file(tmp_path)
    monkeypatch.setenv("TRANSLITO_CODESWITCH_MODEL_DIR", str(tmp_path))
    factory = Mock()
    monkeypatch.setattr(faster_whisper, "WhisperModel", factory)
    with block_network():
        recognizer = load_cached_codeswitch()
    assert recognizer.provider == "arabic-codeswitch-ct2"
    assert factory.call_args.args == (str(tmp_path),)
    assert factory.call_args.kwargs["local_files_only"] is True
