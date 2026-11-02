"""Bidi formatting is display-only; persist the original Unicode text."""
import unicodedata

from engines.protect import latin_ranges


FSI, PDI = "\u2068", "\u2069"


def display_text(text):
    pieces, offset = [], 0
    for start, end in latin_ranges(text):
        pieces.extend((text[offset:start], FSI, text[start:end], PDI))
        offset = end
    pieces.append(text[offset:])
    return "".join(pieces)


def dominant_rtl(text):
    rtl = sum(c.isalpha() and unicodedata.bidirectional(c) in {"R", "AL"} for c in text)
    ltr = sum(c.isalpha() and unicodedata.bidirectional(c) == "L" for c in text)
    return rtl > ltr
