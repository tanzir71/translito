"""Build session routers; disabled services are never instantiated."""
from dataclasses import dataclass

from engines.provider import ProviderBinding
from engines.router import RecognizerRouter, TranslatorRouter
from engines.settings import credential_signature


@dataclass(frozen=True)
class ProviderFactory:
    name: str
    kind: str  # asr | mt | live
    build: object  # (ProviderSettings, CredentialStore) -> ProviderBinding
    title: str = ""
    account_kind: str = "free"
    quota_label: str = ""
    monthly_unit: str = "characters"
    monthly_limit: int = 0
    privacy_note: str = ""
    setup_url: str = ""
    training_required: bool = False
    source_languages: tuple = ()  # Empty means the adapter determines support.
    mixed_speech: bool = False
    translates_to: tuple = ()
    streaming: bool = False
    billing_mode: str = "per_request_min"
    models: tuple = ()
    rate: object = None
    rate_checked_on: str = ""
    min_billed_seconds: float = 0
    language_checked_on: str = ""
    language_evidence: str = ""

    @property
    def display_hourly_rate(self):
        from decimal import Decimal
        return Decimal(".18") if self.name == "soniox" else self.rate.per_audio_hour if self.rate else Decimal(0)

    def unavailable_reason(self, source, target):
        from engines.languages import canonical_code
        source, target = canonical_code(source), canonical_code(target)
        if self.name == "gemini-live" and source != "en" and target != "en":
            return "This preview needs English in the language pair."
        if self.source_languages and source not in self.source_languages:
            return f"Recognition is unavailable for {source}."
        if self.translates_to and target not in self.translates_to:
            return f"Translation is unavailable for {target}."
        return ""


def provider_factories():
    # Importing contracts creates no clients, credentials, models or requests.
    from engines import mt_azure, mt_deepl, mt_google, mt_gemini, asr_cohere_api, asr_groq, interp_gemini_live
    factories = (
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
        ProviderFactory("gemini-live", "live", interp_gemini_live.build, "Gemini Live Translate (free preview)",
                        quota_label="One-way only; free-tier account limits apply", monthly_unit="audio_seconds",
                        privacy_note="Audio is sent to Google; free-tier inputs/outputs may improve its products. Preview quality can vary on rapid language switching.",
                        setup_url="https://ai.google.dev/gemini-api/docs/live-api/live-translate", training_required=True),
    )
    from dataclasses import replace
    from engines.mt_cloud import LANGUAGES
    metadata = {
        "azure": dict(models=("standard",), translates_to=tuple(sorted(LANGUAGES))),
        "deepl": dict(models=(), translates_to=tuple(sorted(LANGUAGES))),
        "google": dict(models=("nmt",), translates_to=tuple(sorted(LANGUAGES))),
        "gemini": dict(models=("gemini-3.1-flash-lite",), translates_to=tuple(sorted(LANGUAGES))),
        "cohere-api": dict(models=("cohere-transcribe-arabic-07-2026",), source_languages=("ar", "en"), mixed_speech=True),
        "groq": dict(models=("whisper-large-v3",), min_billed_seconds=10),
        "gemini-live": dict(streaming=True, mixed_speech=True, billing_mode="audio_sent"),
    }
    from engines.paid_streaming import build_soniox, SONIOX_RATE, RATE_CHECKED_ON
    factories += (ProviderFactory("soniox", "live", build_soniox, "Soniox · recognition and translation", "paid",
        privacy_note="Gated speech and your terms are sent to Soniox. Bills connection time plus text tokens.",
        setup_url="https://console.soniox.com/", mixed_speech=True, streaming=True, billing_mode="open_stream",
        models=("stt-rt-v6",), rate=SONIOX_RATE, rate_checked_on=RATE_CHECKED_ON),)
    from engines.paid_streaming import build_elevenlabs, build_speechmatics
    from engines.usage import Rate
    from decimal import Decimal
    factories += (
        ProviderFactory("elevenlabs", "live", build_elevenlabs, "ElevenLabs Scribe v3 Live + translator", "paid",
            privacy_note="Gated speech is sent to ElevenLabs; recognized text goes to the selected translator.",
            setup_url="https://elevenlabs.io/app/settings/api-keys", mixed_speech=True, streaming=True,
            billing_mode="audio_sent", models=("scribe_v3_live",), rate=Rate(per_audio_hour=Decimal(".22")), rate_checked_on=RATE_CHECKED_ON),
        ProviderFactory("speechmatics", "live", build_speechmatics, "Speechmatics Melia + translator", "paid",
            privacy_note="Gated speech is sent to Speechmatics; recognized text goes to the selected translator.",
            setup_url="https://portal.speechmatics.com/", mixed_speech=True, streaming=True,
            billing_mode="open_stream", models=("melia-1",), rate=Rate(per_audio_hour=Decimal(".40")), rate_checked_on=RATE_CHECKED_ON),
    )
    from engines.language_support import CHECKED_ON, EVIDENCE, supported_codes
    result = []
    for factory in factories:
        factory = replace(factory, **metadata.get(factory.name, {}))
        codes = supported_codes(factory.name)
        result.append(replace(factory, source_languages=codes,
            translates_to=codes if factory.kind == "mt" or factory.name in {"soniox", "gemini-live"} else (),
            language_checked_on=CHECKED_ON, language_evidence=EVIDENCE[factory.name]))
    return tuple(result)



def build_session_routers(recognizer, translator, settings, *, offline_only=False,
                           credentials=None, ledger=None, on_event=None, factories=None, pair=None):
    emit = on_event or (lambda *args: None)
    private = offline_only or settings.profile == "offline" or settings.engine_choice == "local"
    selected = {"asr": [], "mt": []}
    factories = provider_factories() if factories is None else factories
    defaults = settings.resolve(*(pair or ("", "")))
    if defaults["default_mt_provider"] == "local" and defaults["default_mt_model"]:
        select_local = getattr(translator, "select_model", None)
        if callable(select_local):
            select_local(defaults["default_mt_model"])
    factories = sorted(factories, key=lambda factory: factory.name != defaults.get("default_" + factory.kind + "_provider"))
    if settings.profile == "booster":
        emit("hint", "This interpreter profile is not configured. Continuing with the Free fallback.")
    if not private:
        for factory in factories:
            if factory.kind not in selected:
                continue
            preference = settings.provider(factory.name)
            if settings.engine_choice == "free" and preference.account_kind == "paid":
                continue
            if pair and factory.unavailable_reason(*pair):
                continue
            if not preference.enabled:
                continue
            if preference.account_kind == "paid" and (settings.monthly_cap <= 0 or preference.monthly_cap <= 0):
                continue
            if not preference.tested_signature:
                emit("hint", f"{factory.name}: Test the key in Settings before enabling cloud requests.")
                continue
            try:
                if credentials is None:
                    from engines.secrets import CredentialStore
                    credentials = CredentialStore()
                binding = factory.build(preference, credentials)
                model = defaults.get("default_" + factory.kind + "_model")
                if factory.name == defaults.get("default_" + factory.kind + "_provider") and model:
                    if factory.models and model not in factory.models:
                        raise ValueError("Unsupported provider model")
                    select = getattr(binding.engine, "select_model", None)
                    if callable(select):
                        select(model)
                    elif model != getattr(binding.engine, "model", None) and not (factory.models and model in factory.models):
                        raise ValueError("This adapter does not support the chosen model")
            except Exception:
                emit("hint", f"{factory.name}: Provider setup is unavailable. Continuing locally.")
                continue

            def ready(name=factory.name, preference=preference):
                key = credentials.get(name)
                return bool(key and credential_signature(name, key, preference) == preference.tested_signature)

            binding.ready = ready
            binding.enabled, binding.tested = True, True
            binding.monthly_cap = preference.monthly_cap
            selected[factory.kind].append(binding)
    options = dict(offline_only=private, ledger=ledger, total_monthly_cap=settings.monthly_cap, on_event=emit,
                   fallback_on_budget=settings.fallback_on_budget, budget_warn_percent=settings.budget_warn_percent)
    for kind in ("asr", "mt"):
        chosen = defaults.get("default_" + kind + "_provider", "")
        if chosen and chosen != "local" and not any(binding.name == chosen for binding in selected[kind]):
            emit("hint", f"{chosen}: The selected default needs a supported model and tested key. Continuing with available engines.")
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
    mt = TranslatorRouter([*selected["mt"], ProviderBinding.local(translator)], **options)
    for kind, router in (("asr", asr), ("mt", mt)):
        order = getattr(router, "providers", None) or getattr(getattr(router,"router",None),"providers",None)
        if defaults.get("default_" + kind + "_provider") == "local" and order:
            order.sort(key=lambda binding: binding.network)
    return (
        asr,
        mt,
    )


def configured_live_interpreter(settings, *, offline_only=False, credentials=None, ledger=None, on_event=None, pair=None):
    if not offline_only and settings.profile != "offline" and settings.engine_choice == "cloud":
        emit = on_event or (lambda *a: None)
        defaults = settings.resolve(*(pair or ("", "")))
        name = defaults["default_asr_provider"] or "soniox"
        if name == "local" or any(f.name == name and f.kind == "asr" for f in provider_factories()):
            return None
        from engines.engine_status import engine_status
        status = engine_status(settings, pair or ("", ""), block_all=offline_only,
                               usage=ledger.snapshot() if ledger else None)
        if status.reason:
            emit("engine_fallback", status.reason)
            return None
        preference = settings.provider(name)
        if not preference.enabled or not preference.tested_signature:
            emit("hint", f"{name}: Connect and Test the selected provider. Continuing on this PC.")
            return None
        try:
            if credentials is None:
                from engines.secrets import CredentialStore
                credentials = CredentialStore()
            factory = next(factory for factory in provider_factories() if factory.name == name and factory.kind == "live")
            if pair and factory.unavailable_reason(*pair):
                raise ValueError("The provider does not support this pair")
            engine = factory.build(preference, credentials).engine
            if defaults["default_asr_model"]:
                engine.select_model(defaults["default_asr_model"])
            engine.settings = settings
            if name == "soniox":
                engine.native_translation = defaults["default_mt_provider"] in {"", "soniox"}
            if ledger is not None:
                engine.ledger = ledger
            engine.authorized_key()
            return engine
        except Exception:
            emit("hint", "The selected cloud engine is unavailable or its tested key changed. Continuing on this PC.")
            return None
    free_live = settings.engine_choice == "free" and settings.resolve(*(pair or ("", "")))["default_asr_provider"] == "gemini-live"
    if offline_only or (settings.profile != "live-preview" and not free_live):
        return None
    emit = on_event or (lambda *a: None)
    preference = settings.provider("gemini-live")
    if not preference.enabled or not preference.tested_signature:
        emit("hint", "Set up and Test Live Translate in Cloud providers before using this preview. Continuing with Free.")
        return None
    try:
        if credentials is None:
            from engines.secrets import CredentialStore
            credentials = CredentialStore()
        from engines.interp_gemini_live import GeminiLiveInterpreter
        engine = GeminiLiveInterpreter(credentials, preference, ledger=ledger)
        engine.authorized_key()
        return engine
    except Exception:
        emit("hint", "Live Translate needs a tested free-tier key and explicit data-use consent. Continuing with Free.")
        return None
