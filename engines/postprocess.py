"""Conservative, shared rejection of non-speech and decoding loops."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import unicodedata
import zlib


def _normalized(text):
    return " ".join("".join(
        " " if unicodedata.category(c).startswith("P") else c
        for c in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.category(c).startswith("M")
    ).split())


HALLUCINATIONS = tuple(json.loads(
    (Path(__file__).parent / "data" / "hallucinations.json").read_text(encoding="utf-8")))


def compression_ratio(text):
    encoded = text.encode("utf-8")
    return len(encoded) / len(zlib.compress(encoded)) if encoded else 0.0


def collapse_loops(text):
    words = text.split()
    output, loops, i = [], 0, 0
    while i < len(words):
        best = None
        for n in range(1, 5):
            pattern = words[i:i + n]
            if len(pattern) < n:
                break
            end = i + n
            while words[end:end + n] == pattern:
                end += n
            if (end - i) // n > 3 and (best is None or end > best[0]):
                best = (end, pattern)
        if best:
            output.extend(best[1] * 2)
            i = best[0]
            loops += 1
        else:
            output.append(words[i])
            i += 1
    return " ".join(output), loops


@dataclass(frozen=True)
class PostprocessResult:
    text: str
    dropped_reason: str | None = None
    repetition_loops: int = 0


def postprocess(text, *, model_compression_ratio=None, blocklist=HALLUCINATIONS):
    text = text.strip()
    if not text:
        return PostprocessResult("")
    normalized = _normalized(text)
    for phrase in blocklist:
        match = _normalized(phrase)
        if normalized == match or (len(match) >= 10 and
                SequenceMatcher(None, normalized, match, autojunk=False).ratio() >= 0.9):
            return PostprocessResult("", "silence_hallucination")
    cleaned, loops = collapse_loops(text)
    ratio = model_compression_ratio if model_compression_ratio is not None else compression_ratio(text)
    if ratio > 2.4:
        return PostprocessResult("", "compression_ratio", loops)
    return PostprocessResult(cleaned, repetition_loops=loops)
