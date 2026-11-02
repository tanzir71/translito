import pytest

from engines.protect import protect, translate_llm, translate_opus, unescape_translation


@pytest.mark.parametrize("adapter", ["azure", "google", "deepl"])
def test_provider_markup_preserves_mixed_english_and_escapes_html(adapter):
    text = 'هخلص <ال> deployment بعد ال meeting & café "API/v1"'
    protected = protect(text, adapter, latin=True)
    assert "deployment" in protected.spans
    assert "meeting" in protected.spans
    assert "café" in protected.spans
    assert "API/v1" in protected.spans
    assert "&lt;ال&gt;" in protected.text and "&amp;" in protected.text
    assert unescape_translation(protected.text) == text
    assert protected.verify(unescape_translation(protected.text))


def test_opus_restores_terms_and_detects_lost_or_duplicate_placeholders():
    protected = protect("راجع deployment بعد meeting", "opus", latin=True)
    assert protected.restore("Review ⟦1⟧ after ⟦2⟧") == "Review deployment after meeting"
    with pytest.raises(ValueError):
        protected.restore("Review after ⟦2⟧")
    with pytest.raises(ValueError):
        protected.restore("⟦1⟧ ⟦1⟧ ⟦2⟧")


def test_opus_lost_placeholder_fallback_is_visible_and_retranslates_original():
    inputs, hints = [], []

    def translate(text):
        inputs.append(text)
        return "lost markers" if len(inputs) == 1 else "fallback translation"

    assert translate_opus("هخلص deployment", translate, latin=True,
                          on_hint=hints.append) == "fallback translation"
    assert inputs == ["هخلص ⟦1⟧", "هخلص deployment"]
    assert len(hints) == 1


def test_llm_retries_once_and_requires_all_terms_and_occurrences():
    outputs = iter(["finish deploy", "finish ⟦deployment⟧ after ⟦meeting⟧"])
    assert translate_llm("هخلص deployment بعد meeting", lambda _: next(outputs), latin=True) == (
        "finish deployment after meeting")
    calls = []
    with pytest.raises(ValueError, match="after retry"):
        translate_llm("API API", lambda text: calls.append(text) or "API", latin=True)
    assert len(calls) == 2


def test_into_arabic_protects_arabic_text_and_glossary_but_not_all_english():
    protected = protect("نراجع API after the meeting", "opus", other_script=True, terms=["API"])
    assert protected.spans == ("نراجع", "API")
    assert "after the meeting" in protected.text
