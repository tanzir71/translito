"""Explicit provider setup/Test actions, separate from the live session router."""
from dataclasses import dataclass, replace
import os
import time
import wave

import numpy as np

from engines.registry import provider_factories
from engines.router import RecognizerRouter, TranslatorRouter
from engines.settings import (budget, credential_signature, load_engine_settings, save_engine_settings)
from engines.usage import UsageLedger


class SetupError(RuntimeError):
    pass


@dataclass
class TestResult:
    latency_s: float
    text: str
    enabled: bool


class ProviderSetup:
    def __init__(self, *, path=None, credentials=None, ledger=None, factories=None, on_event=None):
        self.path = path
        self.credentials = credentials
        self.ledger = ledger if ledger is not None else UsageLedger()
        self.factories = tuple(provider_factories() if factories is None else factories)
        self.emit = on_event or (lambda *args: None)

    def factory(self, name):
        found = next((factory for factory in self.factories if factory.name == name), None)
        if found is None:
            raise SetupError("Unknown provider.")
        return found

    def store(self):
        if self.credentials is None:
            from engines.secrets import CredentialStore
            self.credentials = CredentialStore()
        return self.credentials

    def _validate(self, name, preference):
        factory = self.factory(name)
        if budget(preference.monthly_cap) != 0:
            raise SetupError("These providers use free allowances only. Their paid cap must remain $0.")
        if preference.account_kind != factory.account_kind:
            raise SetupError("Confirm the provider's free or trial account before testing or enabling it.")
        if factory.training_required and not preference.training_consent:
            raise SetupError("Review and explicitly accept this provider's data-use terms first.")
        return factory

    def save_preference(self, name, preference, *, key=""):
        current = load_engine_settings(self.path)
        previous = current.provider(name)
        self.factory(name)
        if key.strip():
            raise SetupError("Use Test to save and verify a new key.")
        signature = previous.tested_signature
        if (preference.region, preference.account_kind, preference.training_consent) != (
                previous.region, previous.account_kind, previous.training_consent):
            signature = ""
        if preference.enabled:
            self._validate(name, preference)
            stored = self.store().get(name)
            if not stored or not signature or credential_signature(name, stored, preference) != signature:
                raise SetupError("Test this key and account configuration before enabling the provider.")
        values = dict(current.providers)
        values[name] = replace(preference, tested_signature=signature)
        save_engine_settings(replace(current, providers=values), self.path)

    def test(self, name, preference, *, key=""):
        current = load_engine_settings(self.path)
        if current.profile == "offline" or os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
            raise SetupError("Switch to Free or Custom before testing a cloud provider.")
        factory = self._validate(name, preference)
        disabled = replace(preference, enabled=False, tested_signature="")
        values = dict(current.providers)
        values[name] = disabled
        # Invalidate the previous Test before changing a key or making a call.
        save_engine_settings(replace(current, providers=values), self.path)
        try:
            credentials = self.store()
            if key.strip():
                credentials.save(name, key)
            saved_key = credentials.get(name)
            if not saved_key:
                raise SetupError("Enter a key, or save one in Windows Credential Manager first.")
            signature = credential_signature(name, saved_key, disabled)
            binding = factory.build(disabled, credentials)
            if binding.rate is None:
                raise SetupError("This account configuration has no verified free pricing policy.")
            binding.enabled, binding.tested, binding.monthly_cap = True, True, 0
            binding.ready = lambda: credential_signature(name, credentials.get(name) or "", disabled) == signature
            hints = []
            def event(kind, payload):
                if kind == "hint":
                    hints.append(payload)
                self.emit(kind, payload)
            options = dict(ledger=self.ledger, total_monthly_cap=0, on_event=event)
            began = time.perf_counter()
            try:
                if factory.kind == "mt":
                    response = TranslatorRouter([binding], **options).translate(
                        "Good morning", "en", "ar", context=[], glossary={})
                else:
                    from engines.hardware import SPEED_CLIP
                    with wave.open(str(SPEED_CLIP), "rb") as clip:
                        audio = np.frombuffer(clip.readframes(clip.getnframes()), dtype="<i2").astype(np.float32) / 32768
                    response = RecognizerRouter([binding], **options).transcribe(audio, 16000, hint_language="ar")
            except Exception:
                raise SetupError(hints[-1] if hints else "Provider test failed. Check the key, account tier and connection.") from None
            elapsed = time.perf_counter() - began
            if not response.text.strip():
                raise SetupError("The provider returned no text for the public test sample.")
            latest = load_engine_settings(self.path)
            if latest.provider(name) != disabled or not binding.ready():
                raise SetupError("The key or settings changed during Test. Test the current configuration again.")
            values = dict(latest.providers)
            enabled = preference.enabled and latest.profile != "offline"
            values[name] = replace(preference, enabled=enabled, tested_signature=signature)
            save_engine_settings(replace(latest, providers=values), self.path)
            return TestResult(elapsed, response.text, enabled)
        except SetupError:
            raise
        except Exception:
            raise SetupError("Provider setup failed. The service remains disabled; check Credential Manager and your settings.") from None
