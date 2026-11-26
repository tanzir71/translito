"""Authenticated metadata checks. No audio or model inference is sent."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
import time
import threading
from uuid import uuid4

import httpx

from engines.settings import credential_signature, load_engine_settings, save_engine_settings

TITLES = {"soniox": "Soniox", "speechmatics": "Speechmatics", "elevenlabs": "ElevenLabs",
          "gemini": "Gemini", "gemini-live": "Gemini Live", "groq": "Groq", "deepl": "DeepL",
          "google": "Google Translation", "cohere-api": "Cohere", "azure": "Azure Translator"}
CHECKED_ON = "2026-11-26"
_requests, _request_lock = {}, threading.RLock()


class ConnectionError(RuntimeError):
    pass


def check_key(provider, key, *, client=None, region=""):
    title = TITLES[provider]
    bearer = {"Authorization": f"Bearer {key}"}
    endpoints = {
        "soniox": ("https://api.soniox.com/v1/models", bearer, {}),
        "speechmatics": ("https://eu1.asr.api.speechmatics.com/v2/jobs/?limit=1", bearer, {}),
        "elevenlabs": ("https://api.elevenlabs.io/v1/user", {"xi-api-key": key}, {}),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key}, {}),
        "gemini-live": ("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key}, {}),
        "groq": ("https://api.groq.com/openai/v1/models", bearer, {}),
        "cohere-api": ("https://api.cohere.com/v1/models", bearer, {}),
        "deepl": ("https://api-free.deepl.com/v2/usage" if key.endswith(":fx") else "https://api.deepl.com/v2/usage",
                  {"Authorization": f"DeepL-Auth-Key {key}"}, {}),
        "google": ("https://translation.googleapis.com/language/translate/v2/languages", {}, {"key": key}),
    }
    try:
        with nullcontext(client) if client is not None else httpx.Client(timeout=12, follow_redirects=False) as transport:
            if provider == "azure":
                response = transport.post("https://api.cognitive.microsofttranslator.com/translate",
                    params={"api-version": "3.0", "from": "en", "to": "fr"},
                    headers={"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region},
                    json=[{"Text": "a"}])
            else:
                url, headers, params = endpoints[provider]
                response = transport.get(url, headers=headers, params=params)
    except httpx.RequestError:
        raise ConnectionError(f"Couldn't reach {title}. Check your connection.") from None
    if response.status_code in {401, 403}:
        raise ConnectionError(f"That key was rejected by {title}.")
    if response.status_code != 200:
        raise ConnectionError(f"{title} returned an error (code {response.status_code}). Try again later.")
    return True


class CloudConnector:
    def __init__(self, path, credentials, *, client=None, checker=check_key):
        self.path, self.credentials, self.client, self.checker = path, credentials, client, checker

    def connect(self, provider, key="", *, account_kind="paid"):
        from app_config import read_config
        if read_config(self.path).getboolean("NETWORK", "block_all", fallback=False):
            raise ConnectionError("Internet is blocked. Allow internet access to connect a provider.")
        settings = load_engine_settings(self.path)
        preference = settings.provider(provider)
        if account_kind != "paid" and provider in {"gemini", "gemini-live", "cohere-api"} and not preference.training_consent:
            raise ConnectionError("Review the provider's data-use terms in Advanced before connecting a free account.")
        key = key.strip() or self.credentials.get(provider) or ""
        if not key:
            raise ConnectionError("Paste your API key first.")
        request_key, epoch = (str(self.path), provider), uuid4().hex
        with _request_lock:
            _requests[request_key] = epoch
        values = dict(settings.providers)
        disabled = replace(preference, enabled=False, tested_signature="", account_kind=account_kind)
        values[provider] = disabled
        save_engine_settings(replace(settings, providers=values), self.path)
        self.checker(provider, key, client=self.client, region=preference.region)
        # Do not re-enable a key that was replaced or removed while the request ran.
        latest = load_engine_settings(self.path)
        if latest.provider(provider).tested_signature or latest.provider(provider).region != preference.region:
            raise ConnectionError("Provider settings changed. Connect again.")
        with _request_lock:
            if _requests.get(request_key) != epoch:
                raise ConnectionError("Provider settings changed. Connect again.")
            self.credentials.save(provider, key)
            values = dict(latest.providers)
            values[provider] = replace(disabled, enabled=True,
                tested_signature=credential_signature(provider, key, disabled))
            save_engine_settings(replace(latest, providers=values), self.path)
        from settings_store import SettingsStore
        SettingsStore(self.path).update({("ENGINES", provider.replace("-", "_") + "_checked_at"):
            datetime.now(timezone.utc).isoformat()}, sync=True)
        return key[-4:]

    def remove(self, provider):
        with _request_lock:
            _requests[str(self.path), provider] = uuid4().hex
            self.credentials.delete(provider)
            settings = load_engine_settings(self.path)
            values = dict(settings.providers)
            values[provider] = replace(settings.provider(provider), enabled=False, tested_signature="")
            save_engine_settings(replace(settings, providers=values), self.path)

    def status(self, provider):
        settings = load_engine_settings(self.path).provider(provider)
        key = self.credentials.get(provider)
        if not key:
            return "", "", False
        valid = bool(settings.enabled and settings.tested_signature == credential_signature(provider, key, settings))
        from app_config import read_config
        checked = read_config(self.path).get("ENGINES", provider.replace("-", "_") + "_checked_at", fallback="")
        return key[-4:], checked, valid
