from unittest.mock import Mock

import numpy as np

from engines.asr_cohere_local import CohereAccessRequired
from engines.asr_local import LocalConversationRecognizer
from engines.lid import PairLanguageDetector
from engines.types import AsrResult


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
