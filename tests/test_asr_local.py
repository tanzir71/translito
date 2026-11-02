from unittest.mock import Mock
from types import SimpleNamespace

import numpy as np
import pytest

from engines.asr_cohere_local import CohereAccessRequired
from engines.asr_local import LocalConversationRecognizer
from engines.lid import PairLanguageDetector
from engines.types import AsrResult
from model_loading import FastWhisperASR


@pytest.fixture(autouse=True)
def no_real_fallback_weights(monkeypatch):
    import engines.asr_codeswitch
    monkeypatch.setattr(engines.asr_codeswitch, "load_cached_codeswitch",
                        Mock(side_effect=FileNotFoundError("not cached in this test")))


def test_missing_cohere_uses_per_utterance_pair_lid_and_whisper_hotwords():
    model = Mock()
    model.detect_language.side_effect = [("ar", 0.9, [("ar", 0.9), ("en", 0.1)]),
                                        ("en", 0.9, [("ar", 0.1), ("en", 0.9)])]
    whisper = Mock()
    whisper.last_result = None
    whisper.transcribe.side_effect = ["راجع ربليكا", "The API works."]
    glossary = Mock()
    glossary.hotwords.return_value = "replica, API"
    glossary.restore_english.side_effect = [("راجع replica", 1), ("The API works.", 0)]
    cohere = Mock()
    cohere.load.side_effect = CohereAccessRequired("needs setup")
    events = []
    recognizer = LocalConversationRecognizer(whisper, lid=PairLanguageDetector(model),
                                             cohere=cohere, glossary=glossary,
                                             on_event=lambda k, p: events.append((k, p)))
    audio = np.ones(32000, dtype=np.float32)
    first = recognizer.transcribe(audio, 16000)
    second = recognizer.transcribe(audio, 16000)
    assert first.text == "راجع replica" and first.language_tag == "mix"
    assert second.language_tag == "en"
    assert [call.kwargs["language"] for call in whisper.transcribe.call_args_list] == ["ar", "en"]
    assert whisper.transcribe.call_args.kwargs["hotwords"] == "replica, API"
    assert sum(kind == "hint" for kind, _ in events) == 1


def test_runtime_cohere_failure_falls_back_without_losing_the_segment():
    model = Mock()
    model.detect_language.return_value = ("ar", 0.9, [("ar", 0.9), ("en", 0.1)])
    cohere = Mock()
    cohere.transcribe.side_effect = RuntimeError("not enough memory")
    whisper = Mock()
    whisper.last_result = None
    whisper.transcribe.return_value = "هذه جملة عربية"
    recognizer = LocalConversationRecognizer(whisper, lid=PairLanguageDetector(model), cohere=cohere)
    result = recognizer.transcribe(np.ones(32000, dtype=np.float32), 16000)
    assert result.text == "هذه جملة عربية"
    assert result.provider == "faster-whisper"
    whisper.transcribe.assert_called_once()


@pytest.mark.parametrize("beam_size", [1, 3, 5], ids=["fast", "balanced", "best"])
@pytest.mark.parametrize("failure", ["setup", "inference"])
def test_codeswitch_fallback_keeps_selected_decoder_preset(monkeypatch, beam_size, failure):
    import engines.asr_codeswitch

    original_model, fallback_model = Mock(), Mock()
    fallback_model.transcribe.return_value = ([SimpleNamespace(
        text="هذه جملة عربية", avg_logprob=-0.2, no_speech_prob=0.01,
    )], SimpleNamespace(language="ar", language_probability=0.95))
    original = FastWhisperASR(original_model, beam_size=beam_size)
    fallback = FastWhisperASR(fallback_model)
    fallback.provider = "arabic-codeswitch-ct2"
    loader = Mock(return_value=fallback)
    monkeypatch.setattr(engines.asr_codeswitch, "load_cached_codeswitch", loader)
    lid_model = Mock()
    lid_model.detect_language.return_value = ("ar", 0.95, [("ar", 0.95), ("en", 0.05)])
    cohere = Mock()
    if failure == "setup":
        cohere.load.side_effect = CohereAccessRequired("not cached")
    else:
        cohere.transcribe.side_effect = RuntimeError("model unavailable")

    recognizer = LocalConversationRecognizer(original, cohere=cohere,
                                             lid=PairLanguageDetector(lid_model))
    result = recognizer.transcribe(np.ones(32000, dtype=np.float32), 16000)

    assert result.text == "هذه جملة عربية" and result.provider == "arabic-codeswitch-ct2"
    assert fallback_model.transcribe.call_args.kwargs["beam_size"] == beam_size
    assert fallback_model.transcribe.call_args.kwargs["language"] == "ar"
    assert fallback_model.transcribe.call_args.kwargs["condition_on_previous_text"] is False
    loader.assert_called_once_with(device="cpu")
    original_model.transcribe.assert_not_called()
