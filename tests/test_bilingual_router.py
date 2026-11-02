from dataclasses import replace
from unittest.mock import Mock

import pytest

from engines.lid import PairLanguageDetector, decode_language, decode_with_script_check, language_tag, latin_ratio
from engines.router import Conversation, route_utterance, translate_utterance
from engines.types import AsrResult, MtResult


def result(text, language="ar", score=-0.2):
    return AsrResult(text, language, 0.9, language, latin_ratio(text), score, 0.0, 3.0, "fake")


@pytest.mark.parametrize("mode,my,audience,tag,translate,speech,source,target", [
    ("listen", "en", "ar", "en", False, "none", "en", "en"),
    ("listen", "en", "ar", "ar", True, "none", "ar", "en"),
    ("listen", "en", "ar", "mix", True, "none", "ar", "en"),
    ("listen", "ar", "ar", "en", True, "none", "en", "ar"),
    ("listen", "ar", "ar", "ar", False, "none", "ar", "ar"),
    ("listen", "ar", "ar", "mix", True, "none", "en", "ar"),
    ("speak", "en", "ar", "en", True, "voice", "en", "ar"),
    ("speak", "en", "ar", "ar", False, "passthrough", "ar", "ar"),
    ("speak", "en", "ar", "mix", False, "passthrough", "ar", "ar"),
    ("speak", "en", "en", "en", False, "passthrough", "en", "en"),
    ("speak", "en", "en", "ar", True, "voice", "ar", "en"),
    ("speak", "en", "en", "mix", True, "voice", "ar", "en"),
])
def test_full_bilingual_routing_table(mode, my, audience, tag, translate, speech, source, target):
    route = route_utterance(tag, mode, Conversation(my_language=my, audience_language=audience))
    assert (route.translate, route.speech, route.source, route.target) == (translate, speech, source, target)


def test_english_listen_line_never_calls_a_translator():
    translator = Mock()
    text, route = translate_utterance(result("The API works", "en"), "listen", Conversation(), translator)
    assert text == "The API works"
    assert route.translate is False
    translator.translate.assert_not_called()


def test_protection_direction_and_speech_choices():
    assert route_utterance("mix", "listen", Conversation()).protect_latin
    mirrored = route_utterance("mix", "listen", Conversation(my_language="ar"))
    assert mirrored.protect_other_script and mirrored.protect_glossary
    assert route_utterance("ar", "speak", Conversation(same_language_speech="mute")).speech == "mute"
    assert route_utterance("mix", "speak", Conversation(same_language_speech="voice")).speech == "voice"
    assert route_utterance("en", "listen", Conversation(show_both=True)).secondary_target == "ar"


def test_lid_renormalizes_pair_and_applies_hysteresis():
    detector = PairLanguageDetector(None)
    first = detector.restrict([("fr", 0.9), ("en", 0.08), ("ar", 0.02)])
    assert first.language == "en"
    assert first.probability == pytest.approx(0.8)
    ambiguous = detector.restrict({"en": 0.048, "ar": 0.052, "de": 0.9})
    assert ambiguous.language == "en"
    assert ambiguous.margin == pytest.approx(0.04)
    assert decode_language(ambiguous) == "ar"
    assert PairLanguageDetector(None).restrict({"fr": 1}).language == "ar"


def test_script_tags_and_transliteration_hits():
    assert language_tag("Please review the API") == "en"
    assert language_tag("نراجع الخادم اليوم") == "ar"
    assert language_tag("هخلص ال deployment بعد ال meeting") == "mix"
    assert language_tag("راجع ربليكا", transliteration_hits=1) == "mix"
    assert language_tag("café résumé", "fr", acoustic_language="fr") == "fr"
    assert latin_ratio("123 !") == 0


def test_script_mismatch_redecodes_only_once_and_retains_better_logprob():
    decision = PairLanguageDetector(None).restrict({"en": 0.9, "ar": 0.1})
    decode = Mock(side_effect=[result("هذه جملة عربية", "en", -1.5), result("This is English", "ar", -0.2)])
    decoded = decode_with_script_check(decode, decision)
    assert decoded.text == "This is English"
    assert decode.call_count == 2
    assert [c.args[0] for c in decode.call_args_list] == ["en", "ar"]
    assert decoded.language_tag == "en"


def test_redecode_does_not_replace_better_first_result():
    decision = PairLanguageDetector(None).restrict({"en": 0.9, "ar": 0.1})
    decode = Mock(side_effect=[result("جملة عربية", "en", -0.1), result("bad", "ar", -1.2)])
    assert decode_with_script_check(decode, decision).text == "جملة عربية"
    assert decode.call_count == 2
