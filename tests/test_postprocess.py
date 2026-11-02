import pytest

from engines.postprocess import collapse_loops, postprocess
from tools.eval.metrics import repetition_loops


@pytest.mark.parametrize("phrase", ["نحن", "لا يمكن", "we need the", "one two three four"])
def test_ngram_loops_collapse_to_two_occurrences(phrase):
    result, count = collapse_loops("begin " + (phrase + " ") * 8 + "end")
    assert result == "begin " + phrase + " " + phrase + " end"
    assert count == 1
    assert repetition_loops(result) == 0


@pytest.mark.parametrize("text", ["ترجمة نانسي قنقر", "تَرْجَمَة نانسي قنقر!", "اشتركوا في القناة",
                                  "Thanks for watching.", "Subtitles by", "Thank you for watching!"])
def test_known_silence_hallucinations_are_rejected(text):
    result = postprocess(text)
    assert result.text == ""
    assert result.dropped_reason == "silence_hallucination"


def test_normal_speech_is_not_rejected_for_containing_a_blocklisted_phrase():
    text = "Thanks for watching the dashboard while I restart the server."
    assert postprocess(text).text == text


def test_high_compression_is_rejected_even_if_repetitions_can_be_collapsed():
    result = postprocess("لا " * 300)
    assert result.text == ""
    assert result.dropped_reason == "compression_ratio"
    assert postprocess("normal text", model_compression_ratio=2.5).text == ""
