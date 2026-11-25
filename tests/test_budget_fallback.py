from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from engines.provider import ProviderBinding
from engines.router import TranslatorRouter
from engines.types import MtResult
from engines.usage import UsageLedger

@pytest.mark.parametrize("action", ["local", "stop"])
def test_zero_budget_blocks_paid_request_and_honors_fallback(tmp_path, action):
    from decimal import Decimal
    from engines.usage import BudgetExceeded, Rate
    cloud = SimpleNamespace(name="paid", requires_network=True, supports=lambda *a: True,
        translate=Mock(return_value=MtResult("Cloud", "paid")))
    local = SimpleNamespace(name="local", requires_network=False, supports=lambda *a: True,
        translate=Mock(return_value=MtResult("Local", "local")))
    events = []
    router = TranslatorRouter([ProviderBinding(cloud, enabled=True, tested=True, monthly_cap=Decimal(5),
        rate=Rate(per_million_chars=Decimal(10))), ProviderBinding.local(local)],
        ledger=UsageLedger(tmp_path / "usage.json"), total_monthly_cap=Decimal(0), fallback_on_budget=action,
        on_event=lambda k, v: events.append((k, v)))
    if action == "stop":
        with pytest.raises(BudgetExceeded):
            router.translate("Hola", "es", "en", context=[], glossary={})
        local.translate.assert_not_called()
    else:
        assert router.translate("Hola", "es", "en", context=[], glossary={}).text == "Local"
    cloud.translate.assert_not_called()
    assert any(k == "budget" and v["action"] == action for k, v in events)
