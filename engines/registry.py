"""Build session routers; disabled services are never instantiated."""
from dataclasses import dataclass

from engines.provider import ProviderBinding
from engines.router import RecognizerRouter, TranslatorRouter
from engines.settings import credential_signature


@dataclass(frozen=True)
class ProviderFactory:
    name: str
    kind: str  # asr | mt
    build: object  # (ProviderSettings, CredentialStore) -> ProviderBinding
    title: str = ""
    account_kind: str = "free"
    quota_label: str = ""
    monthly_unit: str = "characters"
    monthly_limit: int = 0
    privacy_note: str = ""
    setup_url: str = ""
    training_required: bool = False


def provider_factories():
    # Importing contracts creates no clients, credentials, models or requests.
    from engines import mt_azure, mt_deepl, mt_google, mt_gemini, asr_cohere_api, asr_groq
    return (
        ProviderFactory("azure", "mt", mt_azure.build, "Azure Translator F0", quota_label="2 million characters/month",
                        monthly_limit=2_000_000, privacy_note="Recognized text is sent to Microsoft Translator.",
                        setup_url="https://learn.microsoft.com/azure/ai-services/translator/quickstart-translator"),
        ProviderFactory("deepl", "mt", mt_deepl.build, "DeepL API Free", quota_label="500,000 characters/month",
                        monthly_limit=500_000, privacy_note="Text, context and enabled glossary terms are sent to DeepL.",
                        setup_url="https://developers.deepl.com/docs/getting-started/quickstart"),
        ProviderFactory("google", "mt", mt_google.build, "Google Cloud Translation Basic", quota_label="500,000 characters/month credit",
                        monthly_limit=500_000, privacy_note="Text is sent to Google Cloud. Use a dedicated project; credit is shared with other apps and APIs.",
                        setup_url="https://docs.cloud.google.com/translate/docs/setup"),
        ProviderFactory("gemini", "mt", mt_gemini.build, "Gemini Flash-Lite (free)", quota_label="Account-specific free limits; no paid overage",
                        privacy_note="Google may use free-tier inputs and outputs to improve products. Text, context and terms are uploaded.",
                        setup_url="https://ai.google.dev/gemini-api/docs/api-key", training_required=True),
        ProviderFactory("cohere-api", "asr", asr_cohere_api.build, "Cohere Arabic API trial", "trial", "5 requests/minute; 1,000/month",
                        "requests", 1000, "Cohere may reuse trial audio/text for research and improvement. Trial use is not intended for personal information.",
                        "https://docs.cohere.com/v2/docs/audio-transcription-quickstart", True),
        ProviderFactory("groq", "asr", asr_groq.build, "Groq Whisper (free)", quota_label="20 requests/minute; 8 audio hours/day",
                        monthly_unit="audio_seconds", privacy_note="Audio is sent to Groq. Its account data controls and reliability/abuse retention terms apply.",
                        setup_url="https://console.groq.com/docs/speech-to-text"),
    )


def build_session_routers(recognizer, translator, settings, *, offline_only=False,
                           credentials=None, ledger=None, on_event=None, factories=None):
    emit = on_event or (lambda *args: None)
    private = offline_only or settings.profile == "offline"
    selected = {"asr": [], "mt": []}
    factories = provider_factories() if factories is None else factories
    if settings.profile in {"booster", "live-preview"}:
        emit("hint", "This interpreter profile is not configured. Continuing with the Free fallback.")
    if not private:
        for factory in factories:
            preference = settings.provider(factory.name)
            if not preference.enabled:
                continue
            if not preference.tested_signature:
                emit("hint", f"{factory.name}: Test the key in Settings before enabling cloud requests.")
                continue
            try:
                if credentials is None:
                    from engines.secrets import CredentialStore
                    credentials = CredentialStore()
                binding = factory.build(preference, credentials)
            except Exception:
                emit("hint", f"{factory.name}: Provider setup is unavailable. Continuing locally.")
                continue

            def ready(name=factory.name, preference=preference):
                key = credentials.get(name)
                return bool(key and credential_signature(name, key, preference) == preference.tested_signature)

            binding.ready = ready
            binding.enabled, binding.tested = True, True
            # P3 uses only verified free/trial allowances. Paid connections are
            # reserved for the explicitly enabled P4 booster, not text overage.
            binding.monthly_cap = 0
            selected[factory.kind].append(binding)
    options = dict(offline_only=private, ledger=ledger, total_monthly_cap=settings.monthly_cap, on_event=emit)
    from engines.asr_local import (LocalConversationRecognizer, LocalCohereCandidate,
                                    LocalWhisperCandidate, RoutedConversationRecognizer)
    if selected["asr"] and isinstance(recognizer, LocalConversationRecognizer):
        primary = LocalCohereCandidate(recognizer)
        primary_binding = ProviderBinding.local(primary)
        primary_binding.ready = primary.ready
        candidates = ([*selected["asr"], primary_binding] if settings.profile == "custom" else
                      [primary_binding, *selected["asr"]])
        asr = RoutedConversationRecognizer(recognizer, RecognizerRouter(
            [*candidates, ProviderBinding.local(LocalWhisperCandidate(recognizer))], **options))
    else:
        asr = RecognizerRouter([*selected["asr"], ProviderBinding.local(recognizer)], **options)
    return (
        asr,
        TranslatorRouter([*selected["mt"], ProviderBinding.local(translator)], **options),
    )
