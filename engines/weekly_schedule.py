"""Workday blocks, local clock parsing and migration of old weekly entries."""
from collections import OrderedDict
import ctypes
from datetime import datetime
import re
from zoneinfo import ZoneInfo

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
PRESETS = {"Every day": tuple(range(7)), "Mon–Fri": tuple(range(5)), "Sun–Thu": (6, 0, 1, 2, 3)}


def local_timezone():
    from tzlocal import get_localzone_name
    return get_localzone_name()


def first_weekday(user32=None):
    try:
        api = user32 or ctypes.windll.kernel32
        buffer = ctypes.create_unicode_buffer(8)
        if api.GetLocaleInfoW(0x400, 0x100C, buffer, len(buffer)):
            return int(buffer.value) % 7
    except (AttributeError, OSError, ValueError):
        pass
    return 0


def day_order(first=None):
    first = first_weekday() if first is None else first
    return tuple((first + i) % 7 for i in range(7))


def normalize_time(value):
    value = str(value).strip().lower()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(am|pm)?", value)
    if match:
        hour, minute, meridiem = match.groups()
        hour, minute = int(hour), int(minute)
        if meridiem:
            if not 1 <= hour <= 12:
                raise ValueError("Enter a time like 09:30 or 9:30 pm")
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif re.fullmatch(r"\d{3,4}", value):
        hour, minute = int(value[:-2]), int(value[-2:])
    else:
        raise ValueError("Enter a time like 09:30 or 9:30 pm")
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("Enter a time like 09:30 or 9:30 pm")
    return f"{hour:02d}:{minute:02d}"


def validate_blocks(blocks):
    result, used = [], set()
    if not isinstance(blocks, list):
        raise ValueError("Weekly hours must be a list of day blocks")
    for block in blocks:
        days = sorted(set(block["days"]))
        if not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise ValueError("Keep at least one day selected")
        if used.intersection(days):
            raise ValueError("Each day can have hours in only one block")
        used.update(days)
        zone = block.get("timezone") or local_timezone()
        ZoneInfo(zone)
        result.append(dict(days=days, start=normalize_time(block["start"]), end=normalize_time(block["end"]),
                           timezone=zone, title=str(block.get("title", "Workdays"))))
    return result


def migrate_entries(entries, saved_zone, pc_zone):
    grouped = OrderedDict()
    changed = False
    for entry in entries:
        zone = entry.get("timezone", saved_zone or "UTC")
        if (saved_zone or "UTC") == "UTC" and zone == "UTC" and pc_zone != "UTC":
            zone, changed = pc_zone, True
        key = normalize_time(entry["start"]), normalize_time(entry["end"]), zone
        block = grouped.setdefault(key, dict(days=[], start=key[0], end=key[1], timezone=key[2], title=entry.get("title", "Workdays")))
        block["days"].append(int(entry["weekday"]))
    return validate_blocks(list(grouped.values())), changed


def summary(block):
    days = set(block["days"])
    def join(names):
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    if days == set(range(7)):
        prefix = "Every day"
    elif days == set(range(5)):
        prefix = "Monday to Friday"
    elif len(days) == 5:
        prefix = "Every day except " + join([DAYS[d] for d in range(7) if d not in days])
    else:
        prefix = join([DAYS[d] for d in sorted(days)])
    start, end = normalize_time(block["start"]), normalize_time(block["end"])
    zone = block.get("timezone") or local_timezone()
    city = zone.rsplit("/", 1)[-1].replace("_", " ")
    overnight = " (ends the next day)" if end <= start else ""
    return f"{prefix}, {start} – {end} {city} time{overnight}."
