"""Preserve English technical terms across provider-specific MT encodings."""
from collections import Counter
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import re
import unicodedata


def latin_ranges(text):
    ranges, i = [], 0
    while i < len(text):
        if "LATIN" not in unicodedata.name(text[i], "") or not text[i].isalpha():
            i += 1
            continue
        start = i
        i += 1
        while i < len(text) and (
                (text[i].isalpha() and "LATIN" in unicodedata.name(text[i], ""))
                or text[i].isdigit() or unicodedata.category(text[i]).startswith("M")
                or (text[i] in "._/+:#-" and i + 1 < len(text) and text[i + 1].isascii()
                    and text[i + 1].isalnum())):
            i += 1
        ranges.append((start, i))
    return ranges


def protected_ranges(text, *, latin=False, other_script=False, terms=()):
    ranges = latin_ranges(text) if latin else []
    if other_script:
        start = None
        for i, char in enumerate(text + " "):
            protected = char.isalpha() and "LATIN" not in unicodedata.name(char, "")
            if protected and start is None:
                start = i
            elif not protected and start is not None:
                ranges.append((start, i))
                start = None
    for term in terms:
        if term:
            ranges.extend((match.start(), match.end()) for match in re.finditer(
                r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True)
class ProtectedText:
    text: str
    spans: tuple[str, ...]
    placeholders: tuple[str, ...] = ()

    def verify(self, output):
        return all(output.count(span) >= count for span, count in Counter(self.spans).items())

    def restore(self, output):
        if any(output.count(marker) != 1 for marker in self.placeholders):
            raise ValueError("Translator lost or duplicated a protected placeholder")
        for marker, span in zip(self.placeholders, self.spans):
            output = output.replace(marker, span)
        return output


def protect(text, adapter, *, latin=False, other_script=False, terms=()):
    if adapter not in {"azure", "deepl", "google", "opus", "llm"}:
        raise ValueError("Unknown span-protection adapter")
    ranges = protected_ranges(text, latin=latin, other_script=other_script, terms=terms)
    pieces, spans, markers, position = [], [], [], 0
    html = adapter in {"azure", "deepl", "google"}
    for start, end in ranges:
        pieces.append(escape(text[position:start]) if html else text[position:start])
        span = text[start:end]
        spans.append(span)
        if adapter == "azure":
            pieces.append(f'<span class="notranslate">{escape(span)}</span>')
        elif adapter == "google":
            pieces.append(f'<span translate="no">{escape(span)}</span>')
        elif adapter == "deepl":
            pieces.append(f"<x>{escape(span)}</x>")
        elif adapter == "opus":
            marker = f"⟦{len(spans)}⟧"
            while marker in text:
                marker = "⟦" + marker + "⟧"
            markers.append(marker)
            pieces.append(marker)
        else:
            pieces.append(f"⟦{span}⟧")
        position = end
    pieces.append(escape(text[position:]) if html else text[position:])
    return ProtectedText("".join(pieces), tuple(spans), tuple(markers))


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def unescape_translation(text):
    parser = _TextParser()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def translate_opus(text, translate, *, latin=False, other_script=False, terms=(), on_hint=None):
    protected = protect(text, "opus", latin=latin, other_script=other_script, terms=terms)
    translated = translate(protected.text)
    try:
        return protected.restore(translated)
    except ValueError:
        if on_hint:
            on_hint("Opus-MT lost an English-term placeholder; translating this line without masking.")
        return translate(text)


def translate_llm(text, translate, *, latin=False, other_script=False, terms=()):
    protected = protect(text, "llm", latin=latin, other_script=other_script, terms=terms)
    for _ in range(2):
        output = translate(protected.text)
        if protected.verify(output):
            for span in protected.spans:
                output = output.replace(f"⟦{span}⟧", span)
            return output
    raise ValueError("Translator did not preserve protected English terms after retry")
