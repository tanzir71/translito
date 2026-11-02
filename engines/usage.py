"""Usage estimates. Rates are explicit inputs, never authorization to spend.

The durable, cap-enforcing ledger is added with the provider router in P2.
Local evaluation uses these same calculations without modifying user usage.
"""
from dataclasses import dataclass
from decimal import Decimal
import math


@dataclass(frozen=True)
class Rate:
    per_audio_hour: Decimal = Decimal("0")
    per_million_chars: Decimal = Decimal("0")
    minimum_audio_seconds: float = 0.0


LOCAL_RATE = Rate()
# Baseline local execution has no API bill. Cloud rates must be supplied from
# verified provider/account pricing; no speculative future price is built in.
RATES = {"local": LOCAL_RATE, "faster-whisper": LOCAL_RATE, "opus-mt": LOCAL_RATE}


def estimate_cost(rate: Rate, *, audio_seconds=0.0, characters=0, requests=1):
    if not math.isfinite(audio_seconds) or audio_seconds < 0 or characters < 0 or requests < 0:
        raise ValueError("Usage quantities must be finite and non-negative")
    seconds = max(Decimal(str(audio_seconds)),
                  Decimal(str(rate.minimum_audio_seconds)) * requests)
    return (seconds * rate.per_audio_hour / 3600
            + Decimal(characters) * rate.per_million_chars / 1_000_000)
