"""Documented provider codes, separate from the user's script-aware choices.

Capabilities were checked against the linked public documentation, not inferred
from successful inference. Construction performs no network requests.
"""
from engines.languages import CATALOG, canonical_code, language, whisper_code

CHECKED_ON = "2026-11-26"
EVIDENCE = {
    "soniox": "https://docs.soniox.com/stt/concepts/supported-languages",
    "elevenlabs": "https://elevenlabs.io/docs/overview/capabilities/speech-to-text",
    "speechmatics": "https://docs.speechmatics.com/speech-to-text/languages",
    "gemini": "https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite",
    "azure": "https://learn.microsoft.com/azure/ai-services/translator/language-support",
    "deepl": "https://developers.deepl.com/docs/getting-started/supported-languages",
    "google": "https://cloud.google.com/translate/docs/languages",
    "groq": "https://console.groq.com/docs/speech-to-text",
    "cohere-api": "https://docs.cohere.com/v2/docs/audio-transcription-quickstart",
    "gemini-live": "https://ai.google.dev/gemini-api/docs/live-api/live-translate",
}


def supported_codes(provider):
    if provider not in EVIDENCE:
        return ()
    # Cohere's configured Arabic model is distinct from its general ASR model.
    return tuple(item.code for item in CATALOG
                 if provider != "cohere-api" or item.base_code in {"ar", "en"})


def provider_code(provider, value, *, target=False):
    code = canonical_code(value)
    entry = language(code)
    if entry is None:
        return value
    if provider == "elevenlabs":
        return entry.iso6393[0]
    if provider in {"groq", "whisper", "soniox"}:
        return whisper_code(code)
    if provider == "speechmatics":
        return "cmn" if entry.base_code == "zh" else whisper_code(code)
    if provider == "google":
        return {"zh-Hans": "zh-CN", "zh-Hant": "zh-TW", "nb": "no"}.get(code, code)
    if provider == "deepl":
        if entry.base_code == "zh":
            return code.upper() if target else "ZH"
        return ({"en": "EN-US", "pt": "PT-BR"}.get(code, code.upper())
                if target else code.upper())
    if provider == "gemini-live" and code == "pt":
        return "pt-BR"
    return code


def script_instruction(target):
    return {"zh-Hans": "Write the Chinese translation in Simplified Chinese (Hans).",
            "zh-Hant": "Write the Chinese translation in Traditional Chinese (Hant)."}.get(canonical_code(target), "")
