"""Bidi formatting is display-only; persist the original Unicode text."""
import unicodedata

from engines.protect import latin_ranges
from engines.languages import canonical_code, language


def font_family(code, *, semibold=False):
    return {"zh-Hans": "Microsoft YaHei UI", "zh-Hant": "Microsoft JhengHei UI",
            "ja": "Yu Gothic UI", "ko": "Malgun Gothic"}.get(
                canonical_code(code), "Segoe UI Semibold" if semibold else "Segoe UI")


def wrap_mode(code):
    entry = language(code)
    return "char" if entry and entry.script in {"han", "japanese"} else "word"


def wrap_text(text, code, width, measure=len):
    """Display-only character wrapping for Han/kana; never alter saved text.

    Tk Labels have no Text widget's wrap='char' option. Measure their actual
    font and insert line breaks before passing the display copy to the Label.
    """
    if wrap_mode(code) != "char" or width <= 0:
        return text
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for char in paragraph:
            if line and measure(line + char) > width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return "\n".join(lines)


def configure_language_text(widget, text, code, size, *, semibold=False, displayed=False):
    """One typography path for transcript, subtitle and reply Labels."""
    from tkinter.font import Font
    font = (font_family(code, semibold=semibold), size)
    widget._language_text = (text, code, size, semibold, displayed)
    shown = text if displayed else display_text(text)
    if wrap_mode(code) == "char":
        width = float(widget.cget("wraplength") or 0)
        shown = wrap_text(shown, code, width, Font(widget, font=font).measure)
    widget.configure(text=shown, font=font)


def refresh_language_text(widget):
    if hasattr(widget, "_language_text"):
        text, code, size, semibold, displayed = widget._language_text
        configure_language_text(widget, text, code, size, semibold=semibold, displayed=displayed)


FSI, PDI = "\u2068", "\u2069"


def isolate_latin(text):
    pieces, offset = [], 0
    for start, end in latin_ranges(text):
        pieces.extend((text[offset:start], FSI, text[start:end], PDI))
        offset = end
    pieces.append(text[offset:])
    return "".join(pieces)


def display_text(text):
    if not any(unicodedata.bidirectional(c) in {"R", "AL"} for c in text):
        return text
    from bidi import get_display
    import arabic_reshaper
    # Windows Tk renders isolate controls as missing-glyph boxes. Resolve them
    # explicitly, then remove controls from the display copy. Keep Latin runs
    # intact, and keep the stored transcript in its original logical order.
    direction = next(("R" if unicodedata.bidirectional(c) in {"R", "AL"} else "L"
                      for c in text if unicodedata.bidirectional(c) in {"R", "AL", "L"}), "L")
    reshaper = arabic_reshaper.ArabicReshaper(configuration={
        "delete_harakat": False, "shift_harakat_position": True})
    shaped = reshaper.reshape(text)
    return get_display(isolate_latin(shaped), base_dir=direction).replace(FSI, "").replace(PDI, "")


def dominant_rtl(text):
    rtl = sum(c.isalpha() and unicodedata.bidirectional(c) in {"R", "AL"} for c in text)
    ltr = sum(c.isalpha() and unicodedata.bidirectional(c) == "L" for c in text)
    return rtl > ltr
