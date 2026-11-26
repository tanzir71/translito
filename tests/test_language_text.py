import pytest

from engines.display import font_family, wrap_mode, wrap_text
from engines.protect import protect, apply_preferred_terms
from engines.sentence_assembler import SentenceAssembler


@pytest.mark.parametrize("code,font,text", [
    ("zh-Hans", "Microsoft YaHei UI", "我们可以周四交付吗？"),
    ("zh-Hant", "Microsoft JhengHei UI", "我們可以週四交付嗎？"),
    ("ja", "Yu Gothic UI", "木曜日に納品できますか？"),
    ("ko", "Malgun Gothic", "목요일에 전달할 수 있나요？"),
])
def test_script_typography_and_sentence_boundaries(code, font, text):
    assert font_family(code) == font
    assert SentenceAssembler().push(text, code)[0].text == text
    if code != "ko":
        assert wrap_mode(code) == "char"
        assert wrap_text(text, code, 4).replace("\n", "") == text
        assert all(len(line) <= 4 for line in wrap_text(text, code, 4).splitlines())
    else:
        assert wrap_mode(code) == "word"


@pytest.mark.parametrize("text", ["请检查API再部署。", "先檢查API再部署！", "このAPIを確認してください。"])
def test_glossary_terms_adjacent_to_han_and_kana(text):
    for adapter in ("azure", "google", "deepl", "llm", "opus"):
        assert protect(text, adapter, terms=("API",)).spans == ("API",)
    assert "接口" in apply_preferred_terms(text, {"API": "接口"})
    assert "APIs" == apply_preferred_terms("APIs", {"API": "接口"})


def test_latin_fonts_and_non_cjk_wrapping_stay_the_same():
    for code in ("ar", "en", "nl", "nb", "pl", "sv"):
        assert font_family(code) == "Segoe UI"
        assert wrap_mode(code) == "word"
        assert wrap_text("Keep this line", code, 3) == "Keep this line"


@pytest.mark.parametrize("terminal", ["！", "？"])
def test_fullwidth_sentence_ends_flush_without_waiting(terminal):
    assert SentenceAssembler().push("確認" + terminal, "ja")[0].text.endswith(terminal)
