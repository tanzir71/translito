import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from engines.asr_cohere_local import CohereAccessRequired, CohereLocalRecognizer, select_language


@pytest.mark.parametrize("hint,margin,expected", [("ar", 0.9, "ar"), ("mix", 0.8, "ar"),
                                               ("en", 0.8, "en"), ("en", 0.1, "ar"),
                                               (None, None, "ar")])
def test_cohere_language_tags(hint, margin, expected):
    assert select_language(hint, margin=margin) == expected


def test_vad_negative_audio_is_never_decoded_or_loaded():
    recognizer = CohereLocalRecognizer(detector=SimpleNamespace(contains_speech=lambda *args: False))
    recognizer.load = Mock(side_effect=AssertionError("VAD-negative audio reached model"))
    assert recognizer.transcribe(np.full(16000, 0.2), 16000, hint_language="ar").text == ""
    recognizer.load.assert_not_called()


def test_cohere_decodes_once_with_explicit_language_and_honors_stop():
    import torch

    class Batch(dict):
        def to(self, *args, **kwargs):
            return self

    processor = Mock()
    processor.return_value = Batch(input_features=torch.ones((1, 2, 3)), audio_chunk_index=[(0, None)])
    processor.decode.return_value = ["هخلص deployment بعد meeting"]
    model = Mock()
    model.generate.return_value = SimpleNamespace(sequences=torch.ones((1, 4), dtype=torch.long), scores=None)
    recognizer = CohereLocalRecognizer(processor=processor, model=model,
                                      detector=SimpleNamespace(contains_speech=lambda *args: True))
    stop = threading.Event()
    result = recognizer.transcribe(np.full(32000, 0.2), 16000, hint_language="mix", stop_event=stop)
    assert result.text == "هخلص deployment بعد meeting"
    assert result.language_tag == "mix"
    assert processor.call_args.kwargs["language"] == "ar"
    assert model.generate.call_count == 1
    criterion = model.generate.call_args.kwargs["stopping_criteria"][0]
    assert criterion(None, None) is False
    stop.set()
    assert criterion(None, None) is True
    assert recognizer.transcribe(np.ones(32000), 16000, hint_language="en", stop_event=stop).text == ""
    assert model.generate.call_count == 1


def test_gated_download_reads_token_only_from_credential_store(monkeypatch, tmp_path):
    import model_loading
    import transformers
    credentials = Mock()
    credentials.get.return_value = "hf_test_secret_never_write"
    processor = Mock()
    model = Mock()
    model.to.return_value = model
    model.eval.return_value = model
    processor_factory = Mock(return_value=processor)
    model_factory = Mock(return_value=model)
    monkeypatch.setattr(transformers.AutoProcessor, "from_pretrained", processor_factory)
    monkeypatch.setattr(transformers, "CohereAsrForConditionalGeneration",
                        SimpleNamespace(from_pretrained=model_factory), raising=False)
    download = Mock()
    monkeypatch.setattr(model_loading, "_download_repo_with_progress", download)
    recognizer = CohereLocalRecognizer(offline_only=False, credentials=credentials, cache_dir=tmp_path)
    recognizer.load()
    credentials.get.assert_called_once_with("huggingface")
    assert download.call_args.kwargs["token"] == credentials.get.return_value
    assert processor_factory.call_args.kwargs["token"] == credentials.get.return_value
    assert list(tmp_path.iterdir()) == []
    recognizer.load()
    assert model_factory.call_count == 1


def test_gated_failure_never_exposes_a_token_in_ui_error(monkeypatch):
    import transformers
    credentials = Mock()
    credentials.get.return_value = "hf_secret"
    monkeypatch.setattr(transformers.AutoProcessor, "from_pretrained",
                        Mock(side_effect=RuntimeError("Authorization: hf_secret")))
    monkeypatch.setattr(transformers, "CohereAsrForConditionalGeneration", Mock(), raising=False)
    with pytest.raises(CohereAccessRequired) as error:
        CohereLocalRecognizer(credentials=credentials).load()
    assert "hf_secret" not in str(error.value)


def test_real_cohere_feature_extractor_runs_without_network():
    pytest.importorskip("librosa")
    import torch
    from transformers import CohereAsrFeatureExtractor
    from tools.eval.runtime import block_network
    with block_network():
        extractor = CohereAsrFeatureExtractor()
        features = extractor(np.full(16000, 0.1, dtype=np.float32),
                             sampling_rate=16000, return_tensors="pt")
    assert features["input_features"].ndim == 3
    assert features["input_features"].dtype == torch.float32
    assert features["audio_chunk_index"] == [(0, None)]
