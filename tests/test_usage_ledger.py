from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import subprocess
import sys

import pytest

from engines.usage import (Allowance, BudgetExceeded, MonthlyQuota, RollingQuota, QuotaExceeded,
                            Rate, Units, UsageLedger, UsageUnavailable)


RATE = Rate(per_million_chars=Decimal("10"))


def test_zero_cap_allows_free_allowance_but_blocks_first_paid_character(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    token = ledger.reserve("azure", Units(characters=100), rate=RATE, allowance=Allowance(characters=100))
    assert token.estimated_usd == 0
    ledger.settle(token)
    original = ledger.path.read_bytes()
    with pytest.raises(BudgetExceeded):
        ledger.reserve("azure", Units(characters=1), rate=RATE, allowance=Allowance(characters=100))
    assert ledger.path.read_bytes() == original


def test_pending_requests_survive_restart_and_known_unbilled_release_is_idempotent(tmp_path):
    path = tmp_path / "usage.json"
    ledger = UsageLedger(path)
    token = ledger.reserve("paid", Units(characters=100_000), rate=RATE,
                           monthly_cap=1, total_monthly_cap=1)
    restarted = UsageLedger(path)
    with pytest.raises(BudgetExceeded):
        restarted.reserve("paid", Units(characters=1), rate=RATE, monthly_cap=1, total_monthly_cap=1)
    restarted.settle(token, known_not_billed=True, outcome="auth")
    original = path.read_bytes()
    restarted.settle(token, known_not_billed=True, outcome="auth")
    assert path.read_bytes() == original
    assert restarted.snapshot()["providers"]["paid"]["characters"] == 0
    assert len(json.loads(path.read_text())["events"]) == 2


def test_reported_usage_reduces_reservation_but_retains_the_original_record(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    token = ledger.reserve("mt", Units(characters=100_000), rate=RATE, monthly_cap=1, total_monthly_cap=1)
    ledger.settle(token, actual=Units(characters=40_000))
    data = json.loads(ledger.path.read_text())
    assert data["reservations"][token.id]["units"]["characters"] == 100_000
    assert data["reservations"][token.id]["actual_units"]["characters"] == 40_000
    assert ledger.snapshot()["providers"]["mt"]["characters"] == 40_000
    assert Decimal(ledger.snapshot()["providers"]["mt"]["estimated_usd"]) == Decimal(".4")
    ledger.reserve("mt", Units(characters=60_000), rate=RATE, monthly_cap=1, total_monthly_cap=1)


def test_usage_above_the_reserved_bound_stays_pending_and_blocks_more_spend(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    token = ledger.reserve("mt", Units(characters=100_000), rate=RATE, monthly_cap=1, total_monthly_cap=1)
    with pytest.raises(UsageUnavailable):
        ledger.settle(token, actual=Units(characters=100_001))
    with pytest.raises(BudgetExceeded):
        ledger.reserve("mt", Units(characters=1), rate=RATE, monthly_cap=1, total_monthly_cap=1)
    assert not json.loads(ledger.path.read_text())["reservations"][token.id]["settled"]


def test_parallel_requests_cannot_overshoot_a_shared_cap(tmp_path):
    path = tmp_path / "usage.json"
    def reserve(_):
        try:
            UsageLedger(path).reserve("paid", Units(characters=10_000), rate=RATE,
                                       monthly_cap=1, total_monthly_cap=1)
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(reserve, range(25)))
    assert sum(accepted) == 10
    assert Decimal(UsageLedger(path).snapshot()["providers"]["paid"]["estimated_usd"]) == 1


def test_separate_processes_share_the_reservation_lock(tmp_path):
    path = tmp_path / "usage.json"
    code = """from engines.usage import *
import sys
try:
 UsageLedger(sys.argv[1]).reserve('paid', Units(characters=40000), rate=Rate(per_million_chars=10), monthly_cap=1, total_monthly_cap=1)
 print('reserved')
except BudgetExceeded:
 print('capped')
"""
    processes = [subprocess.Popen([sys.executable, "-B", "-c", code, str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        outputs.append(out.strip())
    assert outputs.count("reserved") == 2
    assert outputs.count("capped") == 2


def test_calendar_rollover_preserves_history_and_settles_original_month(tmp_path):
    now = [datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)]
    ledger = UsageLedger(tmp_path / "usage.json", clock=lambda: now[0])
    november = ledger.reserve("service", Units(characters=20))
    now[0] = datetime(2026, 12, 1, tzinfo=timezone.utc)
    ledger.reserve("service", Units(characters=30))
    ledger.settle(november)
    assert ledger.snapshot("2026-11")["providers"]["service"]["characters"] == 20
    assert ledger.snapshot()["providers"]["service"]["characters"] == 30
    assert len(json.loads(ledger.path.read_text())["events"]) == 3


def test_rolling_quota_survives_restart_and_month_boundary(tmp_path):
    now = [datetime(2026, 11, 30, 23, 59, 40, tzinfo=timezone.utc)]
    path = tmp_path / "usage.json"
    options = dict(windows=(RollingQuota(60, requests=2, audio_seconds=30),))
    first = UsageLedger(path, clock=lambda: now[0]).reserve("asr", Units(audio_seconds=15), **options)
    now[0] += timedelta(seconds=21)
    restarted = UsageLedger(path, clock=lambda: now[0])
    second = restarted.reserve("asr", Units(audio_seconds=15), **options)
    with pytest.raises(QuotaExceeded):
        restarted.reserve("asr", Units(audio_seconds=1), **options)
    restarted.settle(second, known_not_billed=True)
    restarted.reserve("asr", Units(audio_seconds=15), **options)
    restarted.settle(first, actual=Units(audio_seconds=10))
    assert restarted.window_snapshot("asr", 60)["audio_seconds"] == 25
    now[0] += timedelta(seconds=40)
    assert restarted.window_snapshot("asr", 60)["audio_seconds"] == 15
    restarted.reserve("asr", Units(audio_seconds=15), **options)
    assert len(json.loads(path.read_text())["reservations"]) == 4


def test_separate_processes_cannot_bypass_rolling_request_limit(tmp_path):
    path = tmp_path / "usage.json"
    code = """from engines.usage import *
import sys
try:
 UsageLedger(sys.argv[1]).reserve('asr', Units(audio_seconds=15), windows=(RollingQuota(3600, requests=2),))
 print('reserved')
except QuotaExceeded:
 print('quota')
"""
    processes = [subprocess.Popen([sys.executable, "-B", "-c", code, str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        outputs.append(out.strip())
    assert outputs.count("reserved") == 2
    assert outputs.count("quota") == 2


def test_malformed_reservation_history_cannot_be_reset_or_bypassed(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    token = ledger.reserve("service", Units(characters=100))
    data = json.loads(ledger.path.read_text())
    data["reservations"][token.id]["estimated_usd"] = "invalid money"
    ledger.path.write_text(json.dumps(data))
    original = ledger.path.read_bytes()
    with pytest.raises(UsageUnavailable):
        ledger.reserve("service", Units(characters=1))
    assert ledger.path.read_bytes() == original


def test_corrupt_history_is_preserved_and_audio_minimum_is_reserved(tmp_path):
    path = tmp_path / "usage.json"
    path.write_bytes(b"not valid original data")
    with pytest.raises(UsageUnavailable):
        UsageLedger(path).reserve("service", Units(characters=1))
    assert path.read_bytes() == b"not valid original data"
    other = UsageLedger(tmp_path / "audio.json")
    token = other.reserve("audio", Units(audio_seconds=2), rate=Rate(per_audio_hour=Decimal(".111"), minimum_audio_seconds=10),
                          monthly_cap=1, total_monthly_cap=1)
    assert token.estimated_usd == Decimal(".111") * 10 / 3600
    assert other.snapshot()["providers"]["audio"]["audio_seconds"] == 2
    assert other.snapshot()["providers"]["audio"]["billed_audio_seconds"] == 10


def test_quota_is_hard_and_free_requests_work_after_a_paid_cap_was_reduced(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    ledger.reserve("paid", Units(characters=100_000), rate=RATE, monthly_cap=1, total_monthly_cap=1)
    ledger.reserve("free", Units(characters=100), quota=MonthlyQuota(characters=100))
    with pytest.raises(QuotaExceeded):
        ledger.reserve("free", Units(characters=1), quota=MonthlyQuota(characters=100))
    assert ledger.snapshot()["providers"]["free"]["characters"] == 100


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1])
def test_invalid_usage_never_reaches_a_provider(bad):
    with pytest.raises(ValueError):
        Units(audio_seconds=bad)
