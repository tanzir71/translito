"""Read-only iCalendar expansion and deterministic Listen-only scheduling."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
import time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Meeting:
    id: str
    start: datetime
    end: datetime
    title: str = "Meeting"
    has_call_link: bool = False


def calendar_meetings(content, start, end):
    from icalendar import Calendar
    import recurring_ical_events
    result = []
    for event in recurring_ical_events.of(Calendar.from_ical(content)).between(start, end):
        began, ended = event.decoded("DTSTART"), event.decoded("DTEND")
        if not isinstance(began, datetime) or not isinstance(ended, datetime):
            continue
        began = began if began.tzinfo else began.replace(tzinfo=start.tzinfo)
        ended = ended if ended.tzinfo else ended.replace(tzinfo=start.tzinfo)
        link = str(event.get("URL", ""))+" "+str(event.get("DESCRIPTION", ""))
        result.append(Meeting(str(event.get("UID", ""))+began.isoformat(), began, ended,
            str(event.get("SUMMARY", "Meeting")), bool(re.search(r"https?://", link))))
    return sorted(result, key=lambda event:event.start)


def weekly_meetings(entries, start, end, *, default_timezone=None):
    from engines.weekly_schedule import local_timezone, normalize_time
    import hashlib
    import json
    default_timezone = default_timezone or local_timezone()
    result, used = [], set()
    for index, entry in enumerate(entries):
        days = entry.get("days", [int(entry["weekday"])] if "weekday" in entry else [])
        if "days" in entry:
            if used.intersection(days):
                raise ValueError("Each day can have hours in only one block")
            used.update(days)
        zone_name = entry.get("timezone", default_timezone)
        zone = ZoneInfo(zone_name)
        day, last = (start.astimezone(zone)-timedelta(days=1)).date(), end.astimezone(zone).date()
        begin_time, end_time = normalize_time(entry["start"]), normalize_time(entry["end"])
        identity = hashlib.sha256(json.dumps([days,begin_time,end_time,zone_name]).encode()).hexdigest()[:12]
        while day <= last:
            if day.weekday() in days:
                def at(value, date):
                    hour, minute = map(int, value.split(":"))
                    local = datetime(date.year,date.month,date.day,hour,minute,tzinfo=zone)
                    # Spring gaps move forward by the gap; ambiguous hours use
                    # their first occurrence so a block starts only once.
                    from datetime import timezone
                    return local.astimezone(timezone.utc).astimezone(zone)
                began = at(begin_time, day)
                ended = at(end_time, day+timedelta(days=1) if end_time <= begin_time else day)
                if began < end and ended > start:
                    result.append(Meeting(f"weekly-{identity}-{began.isoformat()}",began,ended,entry.get("title","Workdays")))
            day += timedelta(days=1)
    return sorted(result,key=lambda event:event.start)


class CalendarFeed:
    def __init__(self, credentials, *, http=None, clock=time.monotonic):
        self.credentials, self.http, self.clock = credentials, http, clock
        self.content, self.next_refresh = None, 0

    def connect(self, url):
        if not url.startswith("https://") or any(c in url for c in "\r\n"):
            raise ValueError("Use an HTTPS read-only calendar link")
        self.credentials.save("calendar", url)
        self.next_refresh = 0

    def meetings(self, start, end):
        if self.clock() >= self.next_refresh:
            self.next_refresh = self.clock()+900
            try:
                link = self.credentials.get("calendar")
                if link:
                    if self.http is None:
                        from engines.cloud_http import CloudHttp
                        self.http = CloudHttp()
                    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
                        logging.getLogger(name).setLevel(logging.WARNING)
                    content = self.http.get_text(link)
                    calendar_meetings(content, start, end)
                    self.content = content
            except Exception:
                pass
        return calendar_meetings(self.content, start, end) if self.content else []


class Scheduler:
    def __init__(self, *, clock, running, start_listen, stop, app_has_audio, notice=lambda event: None, confirm=lambda event: True):
        self.clock, self.running, self.start_listen, self.stop = clock, running, start_listen, stop
        self.app_has_audio, self.notice, self.confirm = app_has_audio, notice, confirm
        self.active, self.seen, self.last_speech = None, set(), None

    def notify_speech(self):
        self.last_speech = self.clock()

    def tick(self, events, *, enabled=False, lead_seconds=60, wait_for_app_audio=True, stop_rule="end",
             silence_seconds=300, ask_before_start=False, only_with_call_link=False, skipped=()):
        now = self.clock()
        if self.active is not None:
            silent = self.last_speech is not None and (now-self.last_speech).total_seconds() >= silence_seconds
            if now >= self.active.end or (stop_rule == "silence" and silent) or not enabled:
                self.stop()
                self.active = None
            return
        if not enabled or self.running():
            return
        for event in events:
            if event.id in skipped or event.id in self.seen or not event.start-timedelta(seconds=lead_seconds) <= now < event.end:
                continue
            if only_with_call_link and not event.has_call_link:
                continue
            if wait_for_app_audio and not self.app_has_audio():
                continue
            self.seen.add(event.id)
            if ask_before_start and not self.confirm(event):
                continue
            self.start_listen()
            self.active, self.last_speech = event, now
            self.notice(event)
            return
