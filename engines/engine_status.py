"""One explanation shared by the status bar, session fallback and setup page."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class EngineStatus:
    engine: str
    reason: str = ""

    @property
    def text(self):
        return self.engine + (" · " + self.reason if self.reason else "")


def engine_status(settings, pair, *, block_all=False, usage=None, failure="", factories=None):
    from engines.registry import provider_factories
    from engines.cloud_connect import TITLES
    if settings.engine_choice == "local" or settings.profile == "offline":
        return EngineStatus("On this PC")
    if settings.engine_choice != "cloud":
        return EngineStatus("Free cloud allowances")
    provider = settings.resolve(*pair)["default_asr_provider"] or "soniox"
    title = TITLES.get(provider, provider)
    if block_all:
        reason = "internet is blocked"
    elif failure:
        reason = f"{title} " + failure if failure in {"key rejected", "couldn't be reached"} else failure
    else:
        factory = next((f for f in (factories if factories is not None else provider_factories()) if f.name == provider), None)
        preference = settings.provider(provider)
        if factory is None or factory.unavailable_reason(*pair):
            reason = f"{title} doesn't support this language pair"
        elif not preference.enabled or not preference.tested_signature:
            reason = f"{title} isn't connected"
        elif settings.monthly_cap <= 0 or preference.monthly_cap <= 0:
            reason = "needs a monthly budget"
        elif usage and sum(Decimal(v["estimated_usd"]) for v in usage.get("providers", {}).values()) >= settings.monthly_cap:
            reason = "budget used up"
        else:
            return EngineStatus(title)
    return EngineStatus("On this PC", reason)
