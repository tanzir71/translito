"""Bidi formatting is display-only; persist the original Unicode text."""
import unicodedata

from engines.protect import latin_ranges


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
