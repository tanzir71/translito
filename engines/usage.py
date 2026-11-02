"""Cost estimates and a durable reserve-before-request usage ledger.

Rates are explicit inputs, never authorization to spend. Pending reservations
survive a crash and count against caps until known not to have been billed.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from uuid import uuid4


@dataclass(frozen=True)
class Rate:
    per_audio_hour: Decimal = Decimal("0")
    per_million_chars: Decimal = Decimal("0")
    minimum_audio_seconds: float = 0.0
    per_million_input_tokens: Decimal = Decimal("0")
    per_million_output_tokens: Decimal = Decimal("0")


LOCAL_RATE = Rate()
# Baseline local execution has no API bill. Cloud rates must be supplied from
# verified provider/account pricing; no speculative future price is built in.
RATES = {"local": LOCAL_RATE, "faster-whisper": LOCAL_RATE, "opus-mt": LOCAL_RATE}


def estimate_cost(rate: Rate, *, audio_seconds=0.0, characters=0, requests=1,
                  input_tokens=0, output_tokens=0):
    if any(not math.isfinite(value) or value < 0 for value in
           (audio_seconds, characters, requests, input_tokens, output_tokens, rate.minimum_audio_seconds)):
        raise ValueError("Usage quantities must be finite and non-negative")
    prices = [Decimal(str(value)) for value in (rate.per_audio_hour, rate.per_million_chars,
                                               rate.per_million_input_tokens, rate.per_million_output_tokens)]
    if any(not price.is_finite() or price < 0 for price in prices):
        raise ValueError("Rates must be finite and non-negative")
    seconds = max(Decimal(str(audio_seconds)),
                  Decimal(str(rate.minimum_audio_seconds)) * requests)
    return (seconds * prices[0] / 3600 + Decimal(characters) * prices[1] / 1_000_000
            + Decimal(input_tokens) * prices[2] / 1_000_000 + Decimal(output_tokens) * prices[3] / 1_000_000)


class UsageUnavailable(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class QuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Units:
    characters: int = 0
    audio_seconds: float = 0
    requests: int = 1
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("Usage quantities must be finite and non-negative")
            if key != "audio_seconds" and int(value) != value:
                raise ValueError("Character, token and request counts must be integers")


@dataclass(frozen=True)
class Allowance:
    characters: int = 0
    audio_seconds: float = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class MonthlyQuota:
    characters: int | None = None
    audio_seconds: float | None = None
    requests: int | None = None


@dataclass(frozen=True)
class RollingQuota:
    seconds: int
    requests: int | None = None
    audio_seconds: float | None = None


@dataclass(frozen=True)
class Reservation:
    id: str
    provider: str
    month: str
    estimated_usd: Decimal
    units: Units | None = None


_FILE_LOCKS, _FILE_LOCKS_GUARD = {}, threading.Lock()
_COUNTERS = ("characters", "audio_seconds", "billed_audio_seconds", "requests", "input_tokens", "output_tokens")


def _money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid budget or usage amount") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Budget and usage amounts must be finite and non-negative")
    return result


def _incremental_cost(before, amounts, rate, allowance):
    paid = {}
    for key, free in asdict(allowance).items():
        counter = "billed_audio_seconds" if key == "audio_seconds" else key
        used, added, credit = (Decimal(str(value)) for value in (before.get(counter, 0), amounts[counter], free))
        paid[key] = max(Decimal(0), used + added - credit) - max(Decimal(0), used - credit)
    return estimate_cost(rate, **paid, requests=0)


class UsageLedger:
    def __init__(self, path=None, *, clock=None):
        if path is None:
            from app_config import CONFIG_FILE
            path = CONFIG_FILE.parent / "usage.json"
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with _FILE_LOCKS_GUARD:
            self.lock = _FILE_LOCKS.setdefault(os.path.normcase(str(self.path.resolve())), threading.RLock())

    @contextmanager
    def _locked(self):
        # A separate retained lock file remains stable when usage.json is
        # atomically replaced. It also coordinates two installed app processes.
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(self.path.suffix + ".lock").open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                acquired = False
                deadline = time.monotonic() + 5
                try:
                    while not acquired:
                        try:
                            handle.seek(0)
                            if os.name == "nt":
                                import msvcrt
                                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                            else:
                                import fcntl
                                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired = True
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise UsageUnavailable("The usage file is busy. Using a local engine.") from None
                            time.sleep(.02)
                    yield
                finally:
                    if acquired:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "months": {}, "reservations": {}, "events": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if data.get("version") != 1 or not isinstance(data.get("months"), dict) or not isinstance(
                    data.get("reservations"), dict) or not isinstance(data.get("events"), list):
                raise ValueError()
            for month in data["months"].values():
                for stats in month["providers"].values():
                    for counter in _COUNTERS:
                        if not math.isfinite(stats.get(counter, 0)) or stats.get(counter, 0) < 0:
                            raise ValueError()
                    _money(stats.get("estimated_usd", "0"))
            for record in data["reservations"].values():
                if not isinstance(record["settled"], bool):
                    raise ValueError()
                data["months"][record["month"]]["providers"][record["provider"]]
                _money(record["estimated_usd"])
                for counter in _COUNTERS:
                    value = record["units"][counter]
                    if not math.isfinite(value) or value < 0:
                        raise ValueError()
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise UsageUnavailable("Usage history could not be read. It was preserved; using a local engine.") from None

    def _write(self, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError:
            raise UsageUnavailable("Usage could not be saved. Using a local engine.") from None
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def snapshot(self, month=None):
        month = month or self.clock().strftime("%Y-%m")
        with self._locked():
            return self._read()["months"].get(month, {"providers": {}})

    def _window(self, data, provider, seconds, now):
        cutoff = now.timestamp() - seconds
        totals = dict.fromkeys(_COUNTERS, 0)
        legacy_times = {event["id"]: event["at"] for event in data["events"] if event.get("event") == "reserved"}
        for token, record in data["reservations"].items():
            if record["provider"] != provider or record.get("released"):
                continue
            try:
                created = datetime.fromisoformat(record.get("created_utc") or legacy_times[token])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created.timestamp() <= cutoff:
                    continue
                for key, value in record.get("actual_units", record["units"]).items():
                    totals[key] += value
            except (TypeError, KeyError, ValueError):
                raise UsageUnavailable("Usage timestamps could not be read. History was preserved.") from None
        return totals

    def window_snapshot(self, provider, seconds):
        with self._locked():
            return self._window(self._read(), provider, seconds, self.clock())

    def reserve(self, provider, units, *, rate=LOCAL_RATE, allowance=Allowance(), quota=MonthlyQuota(),
                monthly_cap=Decimal("0"), total_monthly_cap=Decimal("0"), windows=()):
        if not re.fullmatch(r"[a-z0-9_-]+", provider):
            raise ValueError("Invalid provider identifier")
        cap, total_cap = _money(monthly_cap), _money(total_monthly_cap)
        amounts = asdict(units)
        amounts["billed_audio_seconds"] = max(units.audio_seconds, rate.minimum_audio_seconds * units.requests)
        # Validate policy values before creating a reservation or contacting a provider.
        estimate_cost(rate, **asdict(units))
        if any(not math.isfinite(v) or v < 0 for v in asdict(allowance).values()):
            raise ValueError("Invalid free allowance")
        with self._locked():
            data = self._read()
            now = self.clock()
            month_key = now.strftime("%Y-%m")
            month = data["months"].setdefault(month_key, {"providers": {}})
            stats = month["providers"].setdefault(provider, {"estimated_usd": "0", **dict.fromkeys(_COUNTERS, 0)})
            for window in windows:
                if not isinstance(window.seconds, int) or window.seconds <= 0:
                    raise ValueError("Invalid quota window")
                used = self._window(data, provider, window.seconds, now)
                for key in ("requests", "audio_seconds"):
                    limit = getattr(window, key)
                    if limit is not None:
                        if not math.isfinite(limit) or limit < 0:
                            raise ValueError("Invalid rolling quota")
                        if used[key] + amounts[key] > limit:
                            raise QuotaExceeded("This provider's short-term quota is used up.")
            for key, limit in asdict(quota).items():
                if limit is not None:
                    if not math.isfinite(limit) or limit < 0:
                        raise ValueError("Invalid monthly quota")
                    if stats.get(key, 0) + amounts[key] > limit:
                        raise QuotaExceeded("This provider's monthly quota is used up.")
            cost = _incremental_cost(stats, amounts, rate, allowance)
            spent = _money(stats["estimated_usd"])
            total = sum((_money(value["estimated_usd"]) for value in month["providers"].values()), Decimal(0))
            if cost > 0 and (spent + cost > cap or total + cost > total_cap):
                raise BudgetExceeded("The monthly spending cap would be exceeded.")
            token = Reservation(uuid4().hex, provider, month_key, cost, units)
            pricing = {"rate": {key: str(value) for key, value in asdict(rate).items()},
                       "allowance": asdict(allowance), "before": {key: stats.get(key, 0) for key in _COUNTERS}}
            for key, value in amounts.items():
                stats[key] = stats.get(key, 0) + value
            stats["estimated_usd"] = str(spent + cost)
            data["reservations"][token.id] = {"provider": provider, "month": month_key, "units": amounts,
                                               "estimated_usd": str(cost), "settled": False, "pricing": pricing,
                                               "created_utc": now.isoformat()}
            data["events"].append({"event": "reserved", "id": token.id, "provider": provider,
                                    "at": now.isoformat(), "month": month_key, "estimated_usd": str(cost)})
            self._write(data)
            return token

    def settle(self, reservation, *, known_not_billed=False, outcome="completed", actual=None):
        if outcome not in {"completed", "auth", "quota", "network", "cancelled", "failed"}:
            raise ValueError("Unknown usage outcome")
        with self._locked():
            data = self._read()
            record = data["reservations"].get(reservation.id)
            if record is None:
                raise UsageUnavailable("The usage reservation could not be found.")
            if record["settled"]:
                return
            stats = data["months"][record["month"]]["providers"][record["provider"]]
            actual_amounts, actual_cost = None, None
            if actual is not None and not known_not_billed:
                pricing = record.get("pricing")
                try:
                    rate = Rate(**{key: Decimal(value) for key, value in pricing["rate"].items()}) if pricing else LOCAL_RATE
                    actual_amounts = asdict(actual)
                    actual_amounts["billed_audio_seconds"] = max(actual.audio_seconds, float(rate.minimum_audio_seconds) * actual.requests)
                    if any(value > record["units"][key] for key, value in actual_amounts.items()):
                        raise ValueError()
                    actual_cost = (_incremental_cost(pricing["before"], actual_amounts, rate, Allowance(**pricing["allowance"]))
                                   if pricing else _money(record["estimated_usd"]))
                    if actual_cost > _money(record["estimated_usd"]):
                        raise ValueError()
                except (ValueError, TypeError, KeyError, InvalidOperation):
                    raise UsageUnavailable("Provider usage exceeded its reservation. Further cloud requests are paused.") from None
                for key, original in record["units"].items():
                    stats[key] = max(0, stats[key] - original + actual_amounts[key])
                stats["estimated_usd"] = str(max(Decimal(0), _money(stats["estimated_usd"]) - _money(record["estimated_usd"]) + actual_cost))
                record.update(actual_units=actual_amounts, actual_estimated_usd=str(actual_cost))
            if known_not_billed:
                for key, value in record["units"].items():
                    stats[key] = max(0, stats[key] - value)
                stats["estimated_usd"] = str(max(Decimal(0), _money(stats["estimated_usd"]) - _money(record["estimated_usd"])))
            record.update(settled=True, outcome=outcome, released=known_not_billed)
            data["events"].append({"event": "settled", "id": reservation.id, "outcome": outcome,
                                    "released": known_not_billed, "at": self.clock().isoformat(),
                                    "actual_units": actual_amounts, "actual_estimated_usd": str(actual_cost) if actual_cost is not None else None})
            self._write(data)
