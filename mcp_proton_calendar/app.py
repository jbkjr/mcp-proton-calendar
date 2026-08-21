import os
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from fastmcp import FastMCP

from mcp_proton_calendar.credentials import describe_sources, get_smtp_password

mcp = FastMCP("proton-calendar")

# Configuration from environment
EMAIL = os.environ.get("PROTON_CALENDAR_EMAIL", "")
FULL_NAME = os.environ.get("PROTON_CALENDAR_FULL_NAME", "")
SMTP_HOST = os.environ.get("PROTON_CALENDAR_SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("PROTON_CALENDAR_SMTP_PORT", "1025"))
SMTP_USER = os.environ.get("PROTON_CALENDAR_SMTP_USER", "")
# The SMTP token is resolved lazily by credentials.get_smtp_password() (keyring
# first, PROTON_CALENDAR_SMTP_PASSWORD as fallback) so that importing this module
# never touches the keychain and a rotated Bridge token is picked up without a
# server restart.


def _to_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC. Treats naive datetimes as local time."""
    if dt.tzinfo is None:
        dt = dt.astimezone()  # interpret as local time
    return dt.astimezone(timezone.utc)


def _format_datetime(dt: datetime, all_day: bool = False) -> str:
    """Format datetime for ICS. Uses DATE for all-day, UTC DATETIME otherwise."""
    if all_day:
        return dt.strftime("%Y%m%d")
    return _to_utc(dt).strftime("%Y%m%dT%H%M%SZ")


def _generate_ics(
    method: str,
    uid: str,
    summary: str,
    start_time: datetime,
    end_time: datetime,
    location: Optional[str] = None,
    description: Optional[str] = None,
    all_day: bool = False,
    sequence: int = 0,
    status: str = "CONFIRMED",
    attendees: Optional[list[str]] = None,
) -> str:
    """Generate an ICS calendar string."""
    dt_prefix = "VALUE=DATE:" if all_day else ":"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//mcp-proton-calendar//EN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART{dt_prefix}{_format_datetime(start_time, all_day)}",
        f"DTEND{dt_prefix}{_format_datetime(end_time, all_day)}",
        f"SUMMARY:{summary}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{status}",
    ]
    if attendees:
        lines.append(f"ORGANIZER;CN={FULL_NAME}:mailto:{EMAIL}")
        for attendee in attendees:
            lines.append(f"ATTENDEE;RSVP=TRUE:mailto:{attendee}")
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def _send_ics_email(
    subject: str,
    ics_content: str,
    method: str,
    recipients: Optional[list[str]] = None,
) -> None:
    """Send an ICS calendar invitation email via Proton Bridge."""
    smtp_password = get_smtp_password()
    if not smtp_password:
        raise RuntimeError(
            f"No Proton Bridge SMTP credential found. Checked {describe_sources()}."
        )

    all_recipients = [EMAIL]
    if recipients:
        all_recipients.extend(recipients)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FULL_NAME} <{EMAIL}>"
    msg["To"] = ", ".join(all_recipients)
    msg["Subject"] = subject

    # Plain text fallback
    text_part = MIMEText(
        "This is a calendar invitation.",
        "plain",
        "utf-8",
    )
    msg.attach(text_part)

    # Inline ICS as text/calendar so mail clients recognize it
    ics_part = MIMEText(ics_content, "calendar", "utf-8")
    ics_part.set_param("method", method)
    msg.attach(ics_part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, smtp_password)
        server.sendmail(EMAIL, all_recipients, msg.as_bytes())


@mcp.tool()
def create_proton_calendar_event(
    summary: str,
    start_time: datetime,
    end_time: datetime,
    location: Optional[str] = None,
    description: Optional[str] = None,
    all_day: bool = False,
    attendees: Optional[list[str]] = None,
) -> str:
    """Create a new event on Proton Calendar by sending an ICS invitation email.

    The user will need to click 'Add to calendar' in Proton Mail to confirm the event.

    Args:
        summary: Event title/summary
        start_time: Event start time (ISO format datetime)
        end_time: Event end time (ISO format datetime)
        location: Event location (optional)
        description: Event description (optional)
        all_day: Whether this is an all-day event (optional, default False)
        attendees: List of email addresses to invite (optional). When provided,
            invitees receive the event as an invitation they can accept/decline.
    """
    uid = f"{uuid.uuid4()}@mcp-proton-calendar"
    method = "REQUEST" if attendees else "PUBLISH"

    ics_content = _generate_ics(
        method=method,
        uid=uid,
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        location=location,
        description=description,
        all_day=all_day,
        attendees=attendees,
    )

    _send_ics_email(
        f"Calendar: {summary}",
        ics_content,
        method=method,
        recipients=attendees,
    )

    return (
        f"Event created successfully.\n"
        f"UID: {uid}\n"
        f"Summary: {summary}\n"
        f"Start: {start_time}\n"
        f"End: {end_time}\n"
        + (f"Attendees: {', '.join(attendees)}\n" if attendees else "")
    )


@mcp.tool()
def update_proton_calendar_event(
    event_uid: str,
    summary: str,
    start_time: datetime,
    end_time: datetime,
    sequence: int = 1,
    location: Optional[str] = None,
    description: Optional[str] = None,
    all_day: bool = False,
    attendees: Optional[list[str]] = None,
) -> str:
    """Update an existing Proton Calendar event by sending an updated ICS invitation.

    The user will need to click 'Add to calendar' in Proton Mail to apply the update.

    Args:
        event_uid: The UID of the event to update (from create_proton_calendar_event)
        summary: Updated event title/summary
        start_time: Updated start time (ISO format datetime)
        end_time: Updated end time (ISO format datetime)
        sequence: Sequence number for the update (should increment from previous, default 1)
        location: Updated event location (optional)
        description: Updated event description (optional)
        all_day: Whether this is an all-day event (optional, default False)
        attendees: List of email addresses to invite (optional)
    """
    method = "REQUEST" if attendees else "PUBLISH"

    ics_content = _generate_ics(
        method=method,
        uid=event_uid,
        summary=summary,
        start_time=start_time,
        end_time=end_time,
        location=location,
        description=description,
        all_day=all_day,
        sequence=sequence,
        attendees=attendees,
    )

    _send_ics_email(
        f"Calendar Update: {summary}",
        ics_content,
        method=method,
        recipients=attendees,
    )

    return (
        f"Event update sent successfully.\n"
        f"UID: {event_uid}\n"
        f"Summary: {summary}\n"
        f"Sequence: {sequence}\n"
    )


@mcp.tool()
def cancel_proton_calendar_event(
    event_uid: str,
    summary: str,
) -> str:
    """Cancel an existing Proton Calendar event by sending a cancellation ICS.

    The user will need to open the email in Proton Mail to process the cancellation.

    Args:
        event_uid: The UID of the event to cancel (from create_proton_calendar_event)
        summary: The event title/summary (for the cancellation email subject)
    """
    now = datetime.now(timezone.utc)
    ics_content = _generate_ics(
        method="CANCEL",
        uid=event_uid,
        summary=summary,
        start_time=now,
        end_time=now,
        status="CANCELLED",
        sequence=99,
    )

    _send_ics_email(f"Calendar Cancellation: {summary}", ics_content, method="CANCEL")

    return (
        f"Event cancellation sent successfully.\n"
        f"UID: {event_uid}\n"
        f"Summary: {summary}\n"
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
