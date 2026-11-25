from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
from engines.schedule import CalendarFeed, Scheduler, calendar_meetings, weekly_meetings


def test_recurring_timezone_calendar_starts_and_stops_listen_only_on_fake_clock():
    clock = [datetime(2026,11,25,14,59,tzinfo=ZoneInfo("Asia/Dhaka"))]
    content = (Path(__file__).parent / "fixtures/schedule.ics").read_text()
    events = calendar_meetings(content, clock[0]-timedelta(days=1), clock[0]+timedelta(days=16))
    assert len(events) == 3 and events[0].start.hour == 15
    start, stop, notice, audio = Mock(), Mock(), Mock(), [False]
    scheduler = Scheduler(clock=lambda:clock[0], running=lambda:False, start_listen=start, stop=stop,
        app_has_audio=lambda:audio[0], notice=notice)
    scheduler.tick(events, enabled=True)
    start.assert_not_called()
    audio[0] = True
    scheduler.tick(events, enabled=True)
    start.assert_called_once_with()
    notice.assert_called_once()
    clock[0] = events[0].end
    scheduler.tick(events, enabled=True)
    stop.assert_called_once()


def test_weekly_times_and_private_calendar_link_never_need_config(tmp_path):
    now = datetime(2026,11,25,tzinfo=ZoneInfo("UTC"))
    events = weekly_meetings([dict(weekday=2,start="15:00",end="16:00",timezone="Asia/Dhaka")], now, now+timedelta(days=1))
    assert len(events) == 1 and events[0].start.utcoffset() == timedelta(hours=6)
    keys = {}
    credentials = SimpleNamespace(save=lambda k,v:keys.update({k:v}),get=lambda k:keys[k])
    http = SimpleNamespace(get_text=Mock(return_value=(Path(__file__).parent/"fixtures/schedule.ics").read_text()))
    clock = [0]
    feed = CalendarFeed(credentials,http=http,clock=lambda:clock[0])
    secret = "https://calendar.example/PRIVATE-TOKEN"
    feed.connect(secret)
    assert feed.meetings(now,now+timedelta(days=2))
    assert keys["calendar"] == secret and list(tmp_path.iterdir()) == []
    http.get_text.side_effect = OSError("offline")
    clock[0] = 901
    assert feed.meetings(now,now+timedelta(days=2))
