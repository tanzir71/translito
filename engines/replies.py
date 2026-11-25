"""Short readable replies, validated structured output and a free phrasebook."""
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata


@dataclass(frozen=True)
class Reply:
    native: str
    romanized: str
    meaning: str

    @property
    def spoken(self):
        return self.romanized or self.native


@dataclass
class ReplyResult:
    replies: tuple[Reply, ...]
    provider: str
    usage: object = None


def ascii_romanization(value):
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().split())


def latin_script(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all("LATIN" in unicodedata.name(c, "") for c in letters)


def parse_replies(value):
    values = value.get("replies") if isinstance(value, dict) else None
    if not isinstance(values, list) or not 1 <= len(values) <= 3:
        raise ValueError("Expected one to three short replies")
    result = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("native"), str) or not isinstance(item.get("meaning"), str):
            raise ValueError("Invalid reply fields")
        native, meaning = " ".join(item["native"].split()), " ".join(item["meaning"].split())
        romanized = "" if latin_script(native) else ascii_romanization(item.get("romanized", ""))
        if not native or not meaning or (not latin_script(native) and not romanized) or any(len(v.split()) > 8 for v in (native, romanized, meaning)):
            raise ValueError("Replies must be short and readable")
        result.append(Reply(native, romanized, meaning))
    return tuple(result)


def phrasebook(language, meaning_language="en"):
    data = json.loads((Path(__file__).parent / "data/replies.json").read_text(encoding="utf-8"))
    source, target = data.get(language), data.get(meaning_language, data["en"])
    if not source:
        return ()
    replies = []
    for intent in ("yes", "moment", "repeat"):
        native, romanized = source[intent]
        replies.append(Reply(native, "" if latin_script(native) else romanized, target[intent][0]))
    return tuple(replies)


class ReplyService:
    def __init__(self, translator=None):
        self.translator = translator

    def suggest(self, context, language, meaning_language="en", *, variety="", visible=True):
        if not visible:
            return ReplyResult((), "hidden")
        fallback = phrasebook(language, meaning_language)
        if self.translator is not None:
            try:
                result = self.translator.suggest_replies(context[-3:], language, meaning_language, variety=variety)
                replies = list(result.replies[:2])
                if fallback:
                    replies.append(fallback[-1])  # Always keep one 'please repeat' choice.
                return ReplyResult(tuple(replies), result.provider, result.usage)
            except Exception:
                pass
        return ReplyResult(fallback, "phrasebook")
