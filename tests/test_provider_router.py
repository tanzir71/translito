from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest

from engines.cancellation import GenerationCancelled, generation_scope
from engines.provider import (AuthenticationError, ProviderBinding, ProviderNetworkError, ProviderQuotaError)
from engines.router import RecognizerRouter, TranslatorRouter
from engines.types import AsrResult, MtResult
from engines.usage import Rate, UsageLedger


def binding(name, *, cloud=True, error=None, **kwargs):
    kwargs.setdefault("rate", Rate())  # Explicit free fake, never a live account.
    engine = SimpleNamespace(name=name, requires_network=cloud, supports=lambda *a: True,
                             translate=Mock(side_effect=error, return_value=MtResult("Hello", name)))
    return ProviderBinding(engine, **kwargs)


@pytest.mark.parametrize("error", [AuthenticationError, ProviderQuotaError, ProviderNetworkError])
def test_auth_quota_and_network_errors_fall_through_with_one_hint(error, tmp_path):
    bad = binding("cloud", enabled=True, tested=True, error=error())
    local = binding("local", cloud=False, enabled=True)
    events = []
    router = TranslatorRouter([bad, local], ledger=UsageLedger(tmp_path / "usage.json"),
                               on_event=lambda *a: events.append(a))
    for _ in range(2):
        assert router.translate("مرحبا", "ar", "en", context=[], glossary={}).provider == "local"
    assert bad.engine.translate.call_count == 1 and local.engine.translate.call_count == 2
    assert sum(k == "hint" for k, _ in events) == 1
    assert events[-1] == ("engine", {"mt": "local", "stage": "mt", "fallback": True})


@pytest.mark.parametrize("options", [{"enabled": False, "tested": True}, {"enabled": True, "tested": False},
                                      {"enabled": True, "tested": True, "ready": lambda: False}])
def test_disabled_untested_or_changed_keys_never_make_requests(options, tmp_path):
    cloud = binding("cloud", **options)
    local = binding("local", cloud=False, enabled=True)
    router = TranslatorRouter([cloud, local], ledger=UsageLedger(tmp_path / "usage.json"))
    router.translate("مرحبا", "ar", "en", context=[], glossary={})
    cloud.engine.translate.assert_not_called()
    assert not router.ledger.path.exists()


def test_offline_and_zero_budget_cannot_contact_a_paid_provider(tmp_path):
    cloud = binding("paid", enabled=True, tested=True, rate=Rate(per_million_chars=Decimal(10)))
    local = binding("local", cloud=False, enabled=True)
    ledger = UsageLedger(tmp_path / "usage.json")
    for offline in (True, False):
        router = TranslatorRouter([cloud, local], offline_only=offline, ledger=ledger)
        assert router.translate("Hello", "en", "ar", context=[], glossary={}).provider == "local"
    cloud.engine.translate.assert_not_called()


def test_missing_pricing_policy_fails_closed_even_with_a_tested_key(tmp_path):
    cloud = binding("cloud", enabled=True, tested=True, rate=None)
    local = binding("local", cloud=False, enabled=True)
    router = TranslatorRouter([cloud, local], ledger=UsageLedger(tmp_path / "usage.json"))
    assert router.translate("hello", "en", "ar", context=[], glossary={}).provider == "local"
    cloud.engine.translate.assert_not_called()


def test_unknown_sdk_exception_cannot_echo_key_or_input_into_events_or_history(tmp_path):
    secret = "SENTINEL-PRIVATE-KEY"
    cloud = binding("cloud", enabled=True, tested=True, error=RuntimeError(secret))
    local = binding("local", cloud=False, enabled=True)
    events = []
    ledger = UsageLedger(tmp_path / "usage.json")
    router = TranslatorRouter([cloud, local], ledger=ledger, on_event=lambda *args: events.append(args))
    router.translate("private meeting text", "en", "ar", context=[], glossary={})
    assert secret not in repr(events) + ledger.path.read_text()
    assert "private meeting text" not in ledger.path.read_text()


def test_stop_does_not_try_the_next_provider(tmp_path):
    stop = threading.Event()
    cloud = binding("cloud", enabled=True, tested=True)
    cloud.engine.translate.side_effect = lambda *a, **kw: stop.set() or MtResult("Hello", "cloud")
    local = binding("local", cloud=False, enabled=True)
    router = TranslatorRouter([cloud, local], ledger=UsageLedger(tmp_path / "usage.json"))
    with generation_scope(stop), pytest.raises(GenerationCancelled):
        router.translate("مرحبا", "ar", "en", context=[], glossary={})
    local.engine.translate.assert_not_called()


def test_recognizer_keeps_the_audio_interface_and_falls_back(tmp_path):
    import numpy as np
    cloud = binding("cloud", enabled=True, tested=True)
    cloud.engine.transcribe = Mock(side_effect=ProviderNetworkError())
    local = binding("local", cloud=False, enabled=True)
    local.engine.transcribe = Mock(return_value=AsrResult("مرحبا", "ar", .9, "ar", 0, -.1, 0, 2, "local"))
    router = RecognizerRouter([cloud, local], ledger=UsageLedger(tmp_path / "usage.json"))
    result = router.transcribe(np.ones(32000), 16000, hint_language="ar", prompt=None, stop_event=threading.Event())
    assert result.provider == "local"
    assert local.engine.transcribe.call_args.kwargs["hint_language"] == "ar"
    assert router.ledger.snapshot()["providers"]["cloud"]["audio_seconds"] == 2
