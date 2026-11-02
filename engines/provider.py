"""Provider bindings and public errors that cannot echo SDK credentials."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from engines.usage import Allowance, LOCAL_RATE, MonthlyQuota, Rate


class ProviderError(RuntimeError):
    category = "failed"
    known_not_billed = False
    public_message = "The provider could not complete the request."

    def __init__(self):
        super().__init__(self.public_message)


class AuthenticationError(ProviderError):
    category = "auth"
    known_not_billed = True
    public_message = "The provider key was rejected. Test or replace it in Settings."


class ProviderQuotaError(ProviderError):
    category = "quota"
    known_not_billed = True
    public_message = "The provider quota or request limit was reached."


class ProviderThrottleError(ProviderQuotaError):
    # A local token bucket is checked again on the next utterance; a server
    # quota rejection still gets the normal cooldown.
    cooldown_seconds = 0


class ProviderNetworkError(ProviderError):
    category = "network"
    public_message = "The provider connection failed or timed out."


@dataclass
class ProviderBinding:
    engine: object
    enabled: bool = False
    tested: bool = False
    ready: Callable[[], bool] = lambda: True
    rate: Rate | None = None
    allowance: Allowance = field(default_factory=Allowance)
    quota: MonthlyQuota = field(default_factory=MonthlyQuota)
    monthly_cap: Decimal = Decimal("0")
    windows: tuple = ()

    @property
    def name(self):
        return self.engine.name

    @property
    def network(self):
        return bool(self.engine.requires_network)

    @classmethod
    def local(cls, engine):
        if engine.requires_network:
            raise ValueError("Local bindings must not use the network")
        return cls(engine, enabled=True, tested=True, rate=LOCAL_RATE)
