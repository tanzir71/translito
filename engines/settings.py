"""Non-secret engine preferences. Credentials live only in Credential Manager."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re


PROVIDERS = ("azure", "deepl", "google", "gemini", "cohere-api", "groq", "gemini-live", "soniox", "elevenlabs", "speechmatics")
PROFILES = {"free", "offline", "custom", "booster", "live-preview"}


def budget(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Enter a valid monthly dollar cap") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("The monthly dollar cap must be finite and non-negative")
    return amount


@dataclass(frozen=True)
class ProviderSettings:
    enabled: bool = False
    monthly_cap: Decimal = Decimal("0")
    region: str = ""
    account_kind: str = "unconfirmed"
    tested_signature: str = ""
    training_consent: bool = False


@dataclass(frozen=True)
class EngineSettings:
    profile: str = "free"
    monthly_cap: Decimal = Decimal("0")
    providers: dict = field(default_factory=dict)
    default_asr_provider: str = ""
    default_asr_model: str = ""
    default_mt_provider: str = ""
    default_mt_model: str = ""
    pair_overrides: dict = field(default_factory=dict)
    engine_choice: str = ""
    fallback_on_budget: str = "local"
    budget_warn_percent: int = 80
    _baseline: dict = field(default_factory=dict, compare=False, repr=False)

    def resolve(self, source, target):
        values = {key: getattr(self, key) for key in ("default_asr_provider", "default_asr_model", "default_mt_provider", "default_mt_model")}
        values.update({"default_" + key: value for key, value in self.pair_overrides.get(f"{source}_{target}", {}).items() if value})
        return values

    def provider(self, name):
        return self.providers.get(name, ProviderSettings())


def credential_signature(provider, key, settings):
    # A key/account/region/privacy change invalidates Test immediately. This is
    # a fingerprint of a high-entropy credential, never a copy of the key.
    data = [provider, key.strip(), settings.region, settings.account_kind, settings.training_consent]
    return hashlib.sha256(json.dumps(data, ensure_ascii=True).encode()).hexdigest()


def load_engine_settings(path=None):
    from app_config import read_config, load_runtime_config
    config = read_config(path)
    section = config["ENGINES"] if "ENGINES" in config else {}
    profile = section.get("profile", "offline" if load_runtime_config(path).offline_only else "free")
    profile = profile if profile in PROFILES else "offline"  # Unknown profiles fail private.
    try:
        cap = budget(section.get("monthly_cap_usd", "0"))
    except ValueError:
        cap = Decimal(0)
    providers = {}
    for name in PROVIDERS:
        prefix = name.replace("-", "_") + "_"
        try:
            provider_cap = budget(section.get(prefix + "monthly_cap_usd", "0"))
            enabled = str(section.get(prefix + "enabled", "0")).lower() in {"1", "true", "yes", "on"}
        except ValueError:
            provider_cap, enabled = Decimal(0), False
        signature = section.get(prefix + "tested_signature", "")
        region = section.get(prefix + "region", "")
        account_kind = section.get(prefix + "account_kind", "unconfirmed")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{0,80}", region) or account_kind not in {"unconfirmed", "free", "paid", "trial"}:
            region, account_kind, enabled = "", "unconfirmed", False
        providers[name] = ProviderSettings(
            enabled=enabled, monthly_cap=provider_cap, region=region,
            account_kind=account_kind,
            tested_signature=signature if re.fullmatch(r"[a-f0-9]{64}", signature) else "",
            training_consent=str(section.get(prefix + "training_consent", "0")).lower() in {"1", "true", "yes", "on"})
    defaults = {key: section.get(key, "") for key in ("default_asr_provider", "default_asr_model", "default_mt_provider", "default_mt_model")}
    overrides = {}
    for key, value in section.items():
        match = re.fullmatch(r"pair_([a-z]{2,3}_[a-z]{2,3})_(asr_provider|asr_model|mt_provider|mt_model)", key)
        if match:
            overrides.setdefault(match[1], {})[match[2]] = value
    choice = section.get("engine_choice", "")
    fallback = section.get("fallback_on_budget", "local")
    try:
        warning = min(100, max(1, int(section.get("budget_warn_percent", "80"))))
    except ValueError:
        warning = 80
    settings = EngineSettings(profile, cap, providers, **defaults, pair_overrides=overrides,
        engine_choice=choice if choice in {"cloud", "local", "free"} else "",
        fallback_on_budget=fallback if fallback in {"local", "stop"} else "local", budget_warn_percent=warning)
    object.__setattr__(settings, "_baseline", _values(settings))
    return settings


def _values(settings):
    if settings.profile not in PROFILES:
        raise ValueError("Unknown translation profile")
    values = {"profile": settings.profile, "monthly_cap_usd": str(budget(settings.monthly_cap))}
    values.update(fallback_on_budget=settings.fallback_on_budget, budget_warn_percent=str(settings.budget_warn_percent))
    if settings.engine_choice:
        values["engine_choice"] = settings.engine_choice
    values.update({key: getattr(settings, key) for key in ("default_asr_provider", "default_asr_model", "default_mt_provider", "default_mt_model")})
    for pair, overrides in settings.pair_overrides.items():
        if not re.fullmatch(r"[a-z]{2,3}_[a-z]{2,3}", pair):
            raise ValueError("Invalid language pair override")
        for key, value in overrides.items():
            if key not in {"asr_provider", "asr_model", "mt_provider", "mt_model"}:
                raise ValueError("Invalid engine override")
            values[f"pair_{pair}_{key}"] = value
    for name in PROVIDERS:
        provider = settings.provider(name)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{0,80}", provider.region):
            raise ValueError("Enter a valid provider region")
        if provider.account_kind not in {"unconfirmed", "free", "paid", "trial"}:
            raise ValueError("Choose the provider's account tier")
        if provider.tested_signature and not re.fullmatch(r"[a-f0-9]{64}", provider.tested_signature):
            raise ValueError("Invalid tested-key fingerprint")
        prefix = name.replace("-", "_") + "_"
        values.update({prefix + "enabled": str(int(provider.enabled)),
                       prefix + "monthly_cap_usd": str(budget(provider.monthly_cap)),
                       prefix + "region": provider.region, prefix + "account_kind": provider.account_kind,
                       prefix + "tested_signature": provider.tested_signature,
                       prefix + "training_consent": str(int(provider.training_consent))})
    return values


def save_engine_settings(settings, path=None):
    from app_config import read_config, write_config, _ensure_section
    values = _values(settings)
    if settings._baseline:
        values = {key: value for key, value in values.items() if settings._baseline.get(key) != value}
    config = read_config(path)
    _ensure_section(config, "ENGINES").update(values)
    write_config(config, path)


def migrate_engine_settings(path=None):
    from app_config import append_missing_settings
    settings = load_engine_settings(path)
    append_missing_settings("ENGINES", _values(settings), path)
    return settings
