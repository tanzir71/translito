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


def provider_factories():
    # P3 registers verified REST adapters here. No SDK or credentials are loaded
    # until a service is enabled and has a successful Test fingerprint.
    return ()


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
            selected[factory.kind].append(binding)
    options = dict(offline_only=private, ledger=ledger, total_monthly_cap=settings.monthly_cap, on_event=emit)
    return (
        RecognizerRouter([*selected["asr"], ProviderBinding.local(recognizer)], **options),
        TranslatorRouter([*selected["mt"], ProviderBinding.local(translator)], **options),
    )
