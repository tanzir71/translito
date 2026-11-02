from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines.provider import AuthenticationError, ProviderBinding
from engines.registry import ProviderFactory
from engines.settings import (EngineSettings, ProviderSettings, credential_signature,
                              load_engine_settings, save_engine_settings)
from engines.setup import ProviderSetup, SetupError
from engines.types import MtResult
from engines.usage import LOCAL_RATE, UsageLedger


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    path = tmp_path / "config.ini"
    path.write_bytes(b"; user comment\r\n[OTHER]\r\nunknown = preserve\r\n")
    keys = {}
    credentials = SimpleNamespace(get=Mock(side_effect=keys.get),
                                  save=Mock(side_effect=lambda name, key: keys.update({name: key})))
    engine = SimpleNamespace(name="azure", requires_network=True, supports=lambda *a: True,
                             translate=Mock(return_value=MtResult("صباح الخير", "azure")))
    build = Mock(side_effect=lambda *a: ProviderBinding(engine, rate=LOCAL_RATE))
    factory = ProviderFactory("azure", "mt", build)
    controller = ProviderSetup(path=path, credentials=credentials, factories=[factory],
                               ledger=UsageLedger(tmp_path / "usage.json"))
    return SimpleNamespace(controller=controller, path=path, keys=keys, credentials=credentials,
                           engine=engine, build=build, preference=ProviderSettings(enabled=True, account_kind="free"))


def test_successful_test_is_required_for_enable_and_saves_only_fingerprint(setup):
    item = setup
    with pytest.raises(SetupError, match="Test this key"):
        item.controller.save_preference("azure", item.preference)
    result = item.controller.test("azure", item.preference, key="SENTINEL-PRIVATE-KEY")
    saved = load_engine_settings(item.path).provider("azure")
    assert result.enabled and result.text == "صباح الخير" and result.latency_s >= 0
    assert saved.enabled and saved.monthly_cap == 0
    assert saved.tested_signature == credential_signature("azure", "SENTINEL-PRIVATE-KEY", saved)
    assert "SENTINEL-PRIVATE-KEY" not in item.path.read_text()
    assert item.path.read_bytes().startswith(b"; user comment\r\n[OTHER]\r\nunknown = preserve\r\n")
    item.controller.save_preference("azure", replace(saved, enabled=False))
    item.controller.save_preference("azure", replace(saved, enabled=True))
    assert load_engine_settings(item.path).provider("azure").enabled
    item.keys["azure"] = "changed key"
    with pytest.raises(SetupError, match="Test this key"):
        item.controller.save_preference("azure", saved)


def test_failure_invalidates_previous_test_and_sanitizes_errors(setup):
    item = setup
    item.controller.test("azure", item.preference, key="first-key")
    item.engine.translate.side_effect = AuthenticationError()
    with pytest.raises(SetupError):
        item.controller.test("azure", item.preference, key="second-key")
    saved = load_engine_settings(item.path).provider("azure")
    assert not saved.enabled and not saved.tested_signature
    item.engine.translate.side_effect = RuntimeError("secret-echo-from-sdk")
    with pytest.raises(SetupError) as error:
        item.controller.test("azure", item.preference)
    assert "secret-echo" not in str(error.value)


@pytest.mark.parametrize("guard", ["profile", "environment"])
def test_offline_refuses_test_before_key_save_or_any_mutation(setup, monkeypatch, guard):
    item = setup
    if guard == "profile":
        save_engine_settings(EngineSettings(profile="offline"), item.path)
    else:
        monkeypatch.setenv("OFFLINE_ONLY", "1")
    original = item.path.read_bytes()
    with pytest.raises(SetupError, match="Switch to Free"):
        item.controller.test("azure", item.preference, key="unused")
    item.credentials.save.assert_not_called()
    item.credentials.get.assert_not_called()
    item.build.assert_not_called()
    assert item.path.read_bytes() == original
    assert not item.controller.ledger.path.exists()


def test_account_consent_and_zero_cap_checked_before_any_call(setup):
    item = setup
    item.controller.factories = (replace(item.controller.factories[0], training_required=True),)
    for preference in (item.preference, replace(item.preference, account_kind="paid", training_consent=True),
                       replace(item.preference, monthly_cap=1, training_consent=True)):
        with pytest.raises(SetupError):
            item.controller.test("azure", preference, key="unused")
    item.build.assert_not_called()
    item.credentials.save.assert_not_called()


def test_settings_changed_during_test_cannot_be_enabled(setup):
    item = setup
    def changed(*args, **kwargs):
        current = load_engine_settings(item.path)
        values = dict(current.providers)
        values["azure"] = replace(values["azure"], region="other")
        save_engine_settings(replace(current, providers=values), item.path)
        return MtResult("صباح الخير", "azure")
    item.engine.translate.side_effect = changed
    with pytest.raises(SetupError, match="settings changed"):
        item.controller.test("azure", item.preference, key="fake-key")
    assert not load_engine_settings(item.path).provider("azure").enabled
