import pytest

from engines.sentence_assembler import SentenceAssembler


@pytest.mark.parametrize("punctuation", [".", "?", "!", "؟", "。"])
def test_terminal_punctuation_flushes_whole_sentence(punctuation):
    assembler = SentenceAssembler()
    assert assembler.push("نراجع", "ar", "first") == []
    completed = assembler.push("الخادم" + punctuation, "ar", "second")
    assert completed[0].text == "نراجع الخادم" + punctuation
    assert completed[0].parts == ("first", "second")


def test_idle_timeout_and_character_limit():
    now = [0.0]
    assembler = SentenceAssembler(clock=lambda: now[0])
    assembler.push("unfinished", "en")
    now[0] = 1.49
    assert assembler.poll() == []
    now[0] = 1.5
    assert assembler.poll()[0].text == "unfinished"
    assert assembler.push("x" * 220, "en")[0].text == "x" * 220


def test_language_change_never_merges_sentences():
    assembler = SentenceAssembler()
    assembler.push("Hello", "en")
    assert assembler.push("مرحبا", "ar")[0].text == "Hello"
    assert assembler.flush()[0].text == "مرحبا"
