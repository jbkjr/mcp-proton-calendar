"""iCalendar (RFC 5545) text for one event. Pure: every input is an argument."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

PRODID = "-//mcp-proton-calendar//EN"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ADDRESS = re.compile(r"[^\s<>;:,\"\\@]+@[^\s<>;:,\"\\@]+")


def escape_text(value: str) -> str:
    """RFC 5545 TEXT: line breaks become a literal backslash-n, so a value stays on its property."""
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    value = re.sub(r"\r\n|\r|\n", r"\\n", value)
    return _CONTROL.sub("", value)


def _param(value: str) -> str:
    """A quoted parameter value, which can't hold a double quote or a control character."""
    return '"' + _CONTROL.sub("", value.replace('"', "").replace("\r", "").replace("\n", "")).strip() + '"'


def _mailto(address: str) -> str:
    """A CAL-ADDRESS isn't TEXT and can't be escaped, so a bad one is refused."""
    if not _ADDRESS.fullmatch(address):
        raise ValueError(f"not a plain email address: {address!r}")
    return f"mailto:{address}"


def fold(line: str) -> str:
    """RFC 5545 folding: at most 75 octets per line, never inside a UTF-8 sequence."""
    parts, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            parts.append(current)
            current, size = " ", 1
        current += char
        size += width
    parts.append(current)
    return "\r\n".join(parts)


def _utc(dt: datetime) -> str:
    """UTC DATE-TIME form. Naive datetimes are local time."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _all_day_end(start: datetime, end: datetime) -> date:
    """RFC 5545 DTEND is exclusive, so the event must end after every date it touches.

    A later date at midnight is already exclusive and stays as given. An end with a
    time of day, or on the start date, moves to the next day.
    """
    if end.date() > start.date() and end.time() == time(0):
        return end.date()
    return max(start.date(), end.date()) + timedelta(days=1)


def _dates(start: datetime, end: datetime, all_day: bool) -> list[str]:
    if all_day:
        fmt = "%Y%m%d"
        return [
            f"DTSTART;VALUE=DATE:{start.strftime(fmt)}",
            f"DTEND;VALUE=DATE:{_all_day_end(start, end).strftime(fmt)}",
        ]
    return [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(end)}"]


def build_ics(
    *,
    method: str,
    uid: str,
    summary: str,
    start: datetime,
    end: datetime,
    dtstamp: datetime,
    organizer_email: str,
    organizer_name: str = "",
    location: str | None = None,
    description: str | None = None,
    all_day: bool = False,
    sequence: int = 0,
    status: str = "CONFIRMED",
    attendees: list[str] | None = None,
) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{escape_text(uid)}",
        f"DTSTAMP:{_utc(dtstamp)}",
        *_dates(start, end, all_day),
        f"SUMMARY:{escape_text(summary)}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{status}",
    ]
    if attendees:
        cn = f";CN={_param(organizer_name)}" if organizer_name else ""
        lines.append(f"ORGANIZER{cn}:mailto:{organizer_email}")
        lines.extend(f"ATTENDEE;RSVP=TRUE:{_mailto(attendee)}" for attendee in attendees)
    if location:
        lines.append(f"LOCATION:{escape_text(location)}")
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "".join(f"{fold(line)}\r\n" for line in lines)
