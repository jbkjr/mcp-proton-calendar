"""iCalendar (RFC 5545) text for one event. Pure: every input is an argument."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

PRODID = "-//mcp-proton-calendar//EN"


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
        f"UID:{uid}",
        f"DTSTAMP:{_utc(dtstamp)}",
        *_dates(start, end, all_day),
        f"SUMMARY:{summary}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{status}",
    ]
    if attendees:
        cn = f';CN="{organizer_name}"' if organizer_name else ""
        lines.append(f"ORGANIZER{cn}:mailto:{organizer_email}")
        lines.extend(f"ATTENDEE;RSVP=TRUE:mailto:{attendee}" for attendee in attendees)
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)
