from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from engines.provider import ProviderBinding
from engines.registry import ProviderFactory, build_session_routers
from engines.settings import (EngineSettings, ProviderSettings, credential_signature,
                              load_engine_settings, migrate_engine_settings, save_engine_settings)
from engines.types import AsrResult, MtResult
from engines.usage import LOCAL_RATE, UsageLedger


def test_engine_migration_preserves_original_bytes_and_private_preference(tmp_path):
    path = tmp_path / "config.ini"
    original = b"\xef\xbb\xbf; keep formatting\r\n[RUNTIME]\r\noffline_only = 1\r\n[ENGINES]\r\ncustom_setting = keep\r\n"
    path.write_bytes(original)
    settings = migrate_engine_settings(path)
    assert settings.profile == "offline" and settings.monthly_cap == 0
    assert path.read_bytes().startswith(original)
    assert all(not p.enabled and p.monthly_cap == 0 for p in settings.providers.values())
    first = path.read_bytes()
    migrate_engine_settings(path)
    assert path.read_bytes() == first


def test_test_fingerprint_changes_with_key_or_account_and_no_key_is_saved(tmp_path):
    path = tmp_path / "config.ini"
    preference = ProviderSettings(enabled=True, region="global", account_kind="free")
    secret = "SENTINEL-KEY-NEVER-IN-CONFIG"
    signature = credential_signature("azure", secret, preference)
    assert signature != credential_signature("azure", secret + "changed", preference)
    assert signature != credential_signature("azure", secret, replace(preference, region="eastus"))
    assert signature != credential_signature("azure", secret, replace(preference, account_kind="paid"))
    save_engine_settings(EngineSettings(providers={"azure": replace(preference, tested_signature=signature)}), path)
    assert secret not in path.read_text()
    assert load_engine_settings(path).provider("azure").tested_signature == signature


def test_invalid_stored_budgets_and_profile_fail_closed_without_rewriting(tmp_path):
    path = tmp_path / "config.ini"
    original = "[ENGINES]\nprofile = typo\nmonthly_cap_usd = NaN\nazure_enabled = 1\nazure_monthly_cap_usd = Infinity\n"
    path.write_text(original)
    settings = load_engine_settings(path)
    assert settings.profile == "offline" and settings.monthly_cap == 0
    assert not settings.provider("azure").enabled
    assert path.read_text() == original


def test_registry_skips_disabled_private_and_changed_key_providers(tmp_path):
    credentials = SimpleNamespace(get=Mock(return_value="original key"))
    local_asr = SimpleNamespace(name="local-asr", requires_network=False)
    local_mt = SimpleNamespace(name="local-mt", requires_network=False, supports=lambda *a: True,
                                translate=Mock(return_value=MtResult("Hello", "local-mt")))
    cloud = SimpleNamespace(name="azure", requires_network=True, supports=lambda *a: True,
                             translate=Mock(return_value=MtResult("Cloud hello", "azure")))
    factory = Mock(return_value=ProviderBinding(cloud, rate=LOCAL_RATE))
    preference = ProviderSettings(enabled=True, account_kind="free")
    preference = replace(preference, tested_signature=credential_signature("azure", "original key", preference))
    settings = EngineSettings(providers={"azure": preference})
    spec = ProviderFactory("azure", "mt", factory)
    args = dict(credentials=credentials, ledger=UsageLedger(tmp_path / "usage.json"), factories=[spec])
    _, router = build_session_routers(local_asr, local_mt, replace(settings, profile="offline"), **args)
    factory.assert_not_called()
    router.translate("مرحبا", "ar", "en", context=[], glossary={})
    cloud.translate.assert_not_called()
    _, router = build_session_routers(local_asr, local_mt, settings, **args)
    assert router.translate("مرحبا", "ar", "en", context=[], glossary={}).provider == "azure"
    credentials.get.return_value = "changed key"
    assert router.translate("مرحبا", "ar", "en", context=[], glossary={}).provider == "local-mt"
    assert cloud.translate.call_count == 1
