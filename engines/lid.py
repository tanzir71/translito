"""Per-utterance, pair-restricted language detection and script checks."""
from dataclasses import dataclass, replace
import math
import unicodedata


LATIN_LANGUAGES = {"fr", "es", "de", "it", "pt", "tr", "id", "vi", "nl", "pl", "ro"}


def latin_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return (sum("LATIN" in unicodedata.name(c, "") for c in letters) / len(letters)
            if letters else 0.0)


def language_tag(text, other="ar", *, transliteration_hits=0, acoustic_language=None):
    ratio = latin_ratio(text)
    if other in LATIN_LANGUAGES:
        # Script cannot distinguish English from e.g. French. Preserve acoustic
        # evidence rather than declaring all Latin-script conversations English.
        return acoustic_language if acoustic_language in {"en", other} else "mix"
    if ratio >= 0.85 and not transliteration_hits:
        return "en"
    if ratio <= 0.10 and not transliteration_hits:
        return other
    return "mix"


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    probability: float
    margin: float
    probabilities: dict[str, float]


class PairLanguageDetector:
    def __init__(self, model, other="ar"):
        if other == "en":
            raise ValueError("Choose a non-English conversation language")
        self.model = model
        self.other = other
        self.previous = None

    def restrict(self, probabilities):
        probabilities = dict(probabilities)
        def probability(language):
            value = float(probabilities.get(language, 0.0))
            return max(0.0, value) if math.isfinite(value) else 0.0

        en = probability("en")
        other = probability(self.other)
        total = en + other
        pair = {"en": en / total if total else 0.5,
                self.other: other / total if total else 0.5}
        margin = abs(pair["en"] - pair[self.other])
        selected = max(pair, key=pair.get)
        if margin < 0.2:
            selected = self.previous or self.other
        self.previous = selected
        return LanguageDecision(selected, pair[selected], margin, pair)

    def detect(self, audio):
        _, _, probabilities = self.model.detect_language(audio=audio)
        return self.restrict(probabilities)


def decode_language(decision, other="ar"):
    # Arabic is the matrix language for ambiguous/code-switched segments.
    return other if decision.margin < 0.2 else decision.language


def decode_with_script_check(decode, decision, other="ar"):
    """Decode at most twice and retain the better available log probability."""
    first = decode(decode_language(decision, other))
    ratio = latin_ratio(first.text)
    mismatch = other not in LATIN_LANGUAGES and (
        (decision.language == "en" and ratio <= 0.10 and bool(first.text))
        or (decision.language == other and ratio >= 0.85))
    best = first
    if mismatch:
        second = decode(other if decode_language(decision, other) == "en" else "en")
        if second.avg_logprob is not None and (
                first.avg_logprob is None or second.avg_logprob > first.avg_logprob):
            best = second
    return replace(best, latin_ratio=latin_ratio(best.text),
                   language_tag=language_tag(best.text, other, acoustic_language=best.language))
