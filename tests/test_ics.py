"""ICS output, through the tools. UID and DTSTAMP vary per call, so goldens mask them."""

from __future__ import annotations

import re

from conftest import call, last_sent

CREATE = "create_proton_calendar_event"
UPDATE = "update_proton_calendar_event"
CANCEL = "cancel_proton_calendar_event"


def masked(ics: str) -> list[str]:
    """CRLF-split lines with the volatile values replaced."""
    assert ics.endswith("END:VCALENDAR") or ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    ics = re.sub(r"^DTSTAMP:\d{8}T\d{6}Z", "DTSTAMP:<now>", ics, flags=re.M)
    ics = re.sub(r"^UID:[0-9a-f-]{36}@mcp-proton-calendar", "UID:<new>", ics, flags=re.M)
    return ics.strip("\r\n").split("\r\n")


def event(method: str, *props: str) -> list[str]:
    return [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//mcp-proton-calendar//EN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        *props,
        "END:VEVENT",
        "END:VCALENDAR",
    ]


def ics_of(fake_smtp, tool: str, **args: object) -> list[str]:
    result = call(tool, **args)
    assert result.isError is False, result.content[0].text
    return masked(last_sent(fake_smtp).ics)


def all_day_dates(fake_smtp, start: str, end: str) -> list[str]:
    lines = ics_of(fake_smtp, CREATE, summary="Trip", start_time=start, end_time=end, all_day=True)
    return [line for line in lines if line.startswith("DT") and not line.startswith("DTSTAMP")]


def test_golden_timed_event(server, fake_smtp) -> None:
    assert ics_of(
        fake_smtp, CREATE,
        summary="Lunch", start_time="2026-03-10T12:00:00-06:00", end_time="2026-03-10T13:00:00-06:00",
        location="Cafe", description="Bring notes",
    ) == event(
        "PUBLISH",
        "UID:<new>",
        "DTSTAMP:<now>",
        "DTSTART:20260310T180000Z",
        "DTEND:20260310T190000Z",
        "SUMMARY:Lunch",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        "LOCATION:Cafe",
        "DESCRIPTION:Bring notes",
    )


def test_golden_all_day_event(server, fake_smtp) -> None:
    assert ics_of(
        fake_smtp, CREATE,
        summary="Holiday", start_time="2026-01-02", end_time="2026-01-03", all_day=True,
    ) == event(
        "PUBLISH",
        "UID:<new>",
        "DTSTAMP:<now>",
        "DTSTART;VALUE=DATE:20260102",
        "DTEND;VALUE=DATE:20260103",
        "SUMMARY:Holiday",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
    )


def test_all_day_same_date_gets_a_next_day_end(server, fake_smtp) -> None:
    assert all_day_dates(fake_smtp, "2026-01-02", "2026-01-02") == [
        "DTSTART;VALUE=DATE:20260102",
        "DTEND;VALUE=DATE:20260103",
    ]


def test_all_day_end_at_midnight_is_exclusive(server, fake_smtp) -> None:
    assert all_day_dates(fake_smtp, "2026-01-02", "2026-01-05")[1] == "DTEND;VALUE=DATE:20260105"


def test_all_day_end_with_a_time_covers_that_date(server, fake_smtp) -> None:
    assert all_day_dates(fake_smtp, "2026-01-02T00:00:00", "2026-01-05T23:59:59")[1] == "DTEND;VALUE=DATE:20260106"
    assert all_day_dates(fake_smtp, "2026-01-02T09:00:00", "2026-01-02T17:00:00")[1] == "DTEND;VALUE=DATE:20260103"


def test_all_day_accepts_a_mix_of_naive_and_aware_times(server, fake_smtp) -> None:
    assert all_day_dates(fake_smtp, "2026-01-02", "2026-01-03T10:00:00Z")[1] == "DTEND;VALUE=DATE:20260104"


def test_all_day_month_and_year_rollover(server, fake_smtp) -> None:
    assert all_day_dates(fake_smtp, "2026-12-31", "2026-12-31")[1] == "DTEND;VALUE=DATE:20270101"


def test_golden_event_with_attendees(server, fake_smtp) -> None:
    assert ics_of(
        fake_smtp, CREATE,
        summary="Review", start_time="2026-03-10T12:00:00Z", end_time="2026-03-10T13:00:00Z",
        attendees=["a@example.com", "b@example.com"],
    ) == event(
        "REQUEST",
        "UID:<new>",
        "DTSTAMP:<now>",
        "DTSTART:20260310T120000Z",
        "DTEND:20260310T130000Z",
        "SUMMARY:Review",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        'ORGANIZER;CN="Test Organizer":mailto:me@example.com',
        "ATTENDEE;RSVP=TRUE:mailto:a@example.com",
        "ATTENDEE;RSVP=TRUE:mailto:b@example.com",
    )
    assert last_sent(fake_smtp).recipients == ["me@example.com", "a@example.com", "b@example.com"]


def test_golden_update(server, fake_smtp) -> None:
    assert ics_of(
        fake_smtp, UPDATE,
        event_uid="abc@example.com", summary="Moved", sequence=3,
        start_time="2026-03-11T12:00:00Z", end_time="2026-03-11T13:00:00Z",
    ) == event(
        "PUBLISH",
        "UID:abc@example.com",
        "DTSTAMP:<now>",
        "DTSTART:20260311T120000Z",
        "DTEND:20260311T130000Z",
        "SUMMARY:Moved",
        "SEQUENCE:3",
        "STATUS:CONFIRMED",
    )
    assert last_sent(fake_smtp).message["Subject"] == "Calendar Update: Moved"
