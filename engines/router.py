"""Bilingual routing policy, independent of local/cloud provider selection."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Conversation:
    other_language: str = "ar"
    my_language: str = "en"
    audience_language: str = "ar"
    show_both: bool = False
    keep_english_terms: bool = True
    same_language_speech: str = "passthrough"  # passthrough | voice | mute

    def __post_init__(self):
        if self.other_language == "en" or self.my_language not in {"en", self.other_language}:
            raise ValueError("Conversation must contain English plus one other language")
        if self.audience_language not in {"en", self.other_language}:
            raise ValueError("Audience language must be in the conversation pair")
        if self.same_language_speech not in {"passthrough", "voice", "mute"}:
            raise ValueError("Unknown same-language speech action")


@dataclass(frozen=True)
class Route:
    source: str
    target: str
    translate: bool
    speech: str  # none | passthrough | voice | mute
    protect_latin: bool = False
    protect_other_script: bool = False
    protect_glossary: bool = False
    secondary_target: str | None = None


def route_utterance(tag, mode, conversation):
    other = conversation.other_language
    if tag not in {"en", other, "mix"}:
        raise ValueError(f"Utterance language {tag!r} is outside the conversation pair")
    if mode not in {"listen", "speak"}:
        raise ValueError("Unknown conversation mode")
    output = conversation.my_language if mode == "listen" else conversation.audience_language
    source = "en" if tag == "en" else other
    if mode == "speak" and (tag == output or (tag == "mix" and output == other)):
        return Route(source, output, False, conversation.same_language_speech)
    if tag == output:
        return Route(source, output, False, "none", secondary_target=(
            other if output == "en" else "en") if conversation.show_both else None)
    return Route(
        "en" if tag == "mix" and output == other else source,
        output, True, "voice" if mode == "speak" else "none",
        protect_latin=tag == "mix" and output == "en",
        protect_other_script=tag == "mix" and output == other,
        protect_glossary=output == other and conversation.keep_english_terms,
    )


def translate_utterance(result, mode, conversation, translator, *, context=None, glossary=None):
    """The pass-through branch intentionally never calls a translator."""
    route = route_utterance(result.language_tag, mode, conversation)
    if not route.translate:
        return result.text, route
    translated = translator.translate(result.text, route.source, route.target,
                                      context=context or [], glossary=glossary or {})
    return translated.text, route
