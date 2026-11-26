from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from engines.weekly_schedule import (normalize_time, migrate_entries, validate_blocks, summary,
                                     PRESETS, day_order, first_weekday)
from engines.schedule import weekly_meetings, Scheduler


@pytest.mark.parametrize("value,expected", [("9:30","09:30"),("09:30","09:30"),("0930","09:30"),
    ("9:30 pm","21:30"),("12:00 am","00:00"),("12:15 PM","12:15")])
def test_editable_times_normalize(value, expected):
    assert normalize_time(value) == expected


@pytest.mark.parametrize("value", ["25:00","9:70","tomorrow","00:30 am","930 pm"])
def test_invalid_times_are_rejected(value):
    with pytest.raises(ValueError,match="Enter a time"):
        normalize_time(value)


def test_migration_groups_five_days_and_changes_only_default_utc_zone():
    old = [dict(weekday=day,start="09:30",end="18:00",timezone="UTC") for day in range(5)]
    blocks, changed = migrate_entries(old,"UTC","Asia/Dhaka")
    assert changed and len(blocks) == 1
    assert blocks[0]["days"] == [0,1,2,3,4] and blocks[0]["timezone"] == "Asia/Dhaka"
    blocks, changed = migrate_entries(old,"Europe/Berlin","Asia/Dhaka")
    assert not changed and blocks[0]["timezone"] == "UTC"


@pytest.mark.parametrize("days,text", [([0,1,2,3,4,5,6],"Every day"),([0,1,2,3,4],"Monday to Friday"),
    ([6,0,1,2,3],"Every day except Friday and Saturday"),([0,2,3],"Monday, Wednesday and Thursday")])
def test_workday_summaries(days, text):
    assert summary(dict(days=days,start="09:30",end="18:00",timezone="Asia/Dhaka")) == text+", 09:30 – 18:00 Dhaka time."
    assert "ends the next day" in summary(dict(days=days,start="22:00",end="06:00",timezone="Asia/Dhaka"))


def test_presets_first_weekday_and_duplicate_day_guard():
    assert set(PRESETS["Sun–Thu"]) == {6,0,1,2,3}
    assert day_order(6) == (6,0,1,2,3,4,5)
    def locale(_locale,_type,buffer,_length):
        buffer.value="6"
        return 2
    assert first_weekday(SimpleNamespace(GetLocaleInfoW=locale)) == 6
    block=dict(days=[0],start="09:30",end="18:00",timezone="Asia/Dhaka")
    with pytest.raises(ValueError,match="only one block"):
        validate_blocks([block,block])


def test_overnight_dhaka_and_berlin_dst_blocks():
    dhaka=ZoneInfo("Asia/Dhaka")
    start=datetime(2026,11,22,tzinfo=dhaka)
    events=weekly_meetings([dict(days=[6],start="22:00",end="06:00",timezone="Asia/Dhaka")],start,start+timedelta(days=2))
    assert len(events)==1 and events[0].end.date() > events[0].start.date()
    assert events[0].end-events[0].start == timedelta(hours=8)
    berlin=ZoneInfo("Europe/Berlin")
    events=weekly_meetings([dict(days=[6],start="02:30",end="04:00",timezone="Europe/Berlin")],
        datetime(2026,3,28,tzinfo=berlin),datetime(2026,4,6,tzinfo=berlin))
    assert [e.start.hour for e in events] == [3,2]
    assert events[0].start.utcoffset() == timedelta(hours=2)


def test_skip_one_occurrence_and_allow_start_during_download():
    start=datetime(2026,11,22,9,30,tzinfo=ZoneInfo("Asia/Dhaka"))
    events=weekly_meetings([dict(days=[6],start="09:30",end="18:00",timezone="Asia/Dhaka")],start,start+timedelta(days=1))
    action=Mock()
    scheduler=Scheduler(clock=lambda:start,running=lambda:False,start_listen=action,stop=Mock(),app_has_audio=lambda:True)
    scheduler.tick(events,enabled=True,skipped={events[0].id})
    action.assert_not_called()
    scheduler.tick(events,enabled=True)
    action.assert_called_once()


def test_quiet_startup_command_and_old_run_value_rewrite(monkeypatch):
    import login
    monkeypatch.setattr(login.sys,"frozen",True,raising=False)
    monkeypatch.setattr(login.sys,"executable","C:/Apps/Translito.exe")
    expected='"C:/Apps/Translito.exe" --tray'
    assert login.default_startup_command()==expected
    key=SimpleNamespace(__enter__=lambda self:self,__exit__=lambda *a:None)
    class Key:
        def __enter__(self): return self
        def __exit__(self,*a): pass
    registry=SimpleNamespace(HKEY_CURRENT_USER=1,KEY_READ=1,KEY_SET_VALUE=2,REG_SZ=1,
        OpenKey=lambda *a:Key(),QueryValueEx=lambda *a:(expected.removesuffix(" --tray"),1),SetValueEx=Mock())
    assert login.migrate_startup_command(registry=registry)
    assert registry.SetValueEx.call_args.args[-1] == expected
