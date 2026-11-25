from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from engines.cost_guard import CostGuard, GateDecision
from engines.usage import Rate, UsageLedger


def guard(tmp_path, mode, decision, cap=5):
    provider = SimpleNamespace(name="paid", open_stream=Mock(), push_audio=Mock(return_value=True),
        finalize=Mock(), close_stream=Mock())
    ledger = UsageLedger(tmp_path / "usage.json")
    instance = CostGuard(provider, ledger=ledger, rate=Rate(per_audio_hour=Decimal(".2")),
        monthly_cap=cap, total_monthly_cap=cap, billing_mode=mode, languages=("es", "en"),
        inspect_audio=lambda *a: decision[0])
    return instance, provider, ledger


@pytest.mark.parametrize("mode", ["open_stream", "audio_sent"])
@pytest.mark.parametrize("kind", ["silence", "music"])
def test_two_hours_non_speech_never_opens_or_reserves(tmp_path, mode, kind):
    decision = [GateDecision(.01, "es", .99)]
    instance, provider, ledger = guard(tmp_path, mode, decision)
    audio = np.zeros(16000, np.float32) if kind == "silence" else np.sin(np.arange(16000) * .2).astype(np.float32) * .2
    for _ in range(7200):
        instance.feed(audio)
    instance.stop()
    provider.open_stream.assert_not_called()
    assert ledger.snapshot()["providers"] == {}
    assert instance.captured_seconds == 7200 and instance.sent_seconds == 0


@pytest.mark.parametrize("mode", ["open_stream", "audio_sent"])
def test_long_pause_meeting_bills_at_most_speech_plus_25_percent(tmp_path, mode):
    decision = [GateDecision(.9, "es", .01)]
    instance, provider, ledger = guard(tmp_path, mode, decision)
    frame = np.full(1600, .2, np.float32)
    for _ in range(3):
        decision[0] = GateDecision(.9, "es", .01)
        for _ in range(40):
            instance.feed(frame)
        decision[0] = GateDecision(.01, "es", .99)
        for _ in range(300):
            instance.feed(np.zeros_like(frame))
    instance.stop()
    stats = ledger.snapshot()["providers"]["paid"]
    assert stats["audio_seconds"] <= 12 * 1.25 + 1e-8
    assert provider.open_stream.call_count == 3


@pytest.mark.parametrize("decision", [GateDecision(.99, "fr"), GateDecision(.99, "es", .9)])
def test_other_languages_and_no_speech_never_open(tmp_path, decision):
    instance, provider, _ = guard(tmp_path, "open_stream", [decision])
    instance.feed(np.ones(16000, np.float32))
    provider.open_stream.assert_not_called()


def test_zero_budget_blocks_before_open_or_upload(tmp_path):
    instance, provider, ledger = guard(tmp_path, "open_stream", [GateDecision(.99, "es")], cap=0)
    assert not instance.feed(np.ones(16000, np.float32))
    provider.open_stream.assert_not_called()
    provider.push_audio.assert_not_called()
    assert ledger.snapshot()["providers"] == {}
