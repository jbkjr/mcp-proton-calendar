import inspect
import os
import re
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Optional

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import TypeAdapter
from pydantic_core import ArgsKwargs

from mcp_proton_calendar.credentials import describe_sources, get_smtp_password
from mcp_proton_calendar.ics import build_ics

# The low-level server, because FastMCP's pre_parse_json turns an Optional[str] argument
# such as '{"a": 1}' or 'null' into JSON. TypeAdapter on the function validates as sent.
server = Server("proton-calendar")
_TOOLS: dict[str, tuple[Callable[..., str], TypeAdapter]] = {}
_OUTPUT_SCHEMA = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}

# Configuration from environment
EMAIL = os.environ.get("PROTON_CALENDAR_EMAIL", "").strip()
FULL_NAME = os.environ.get("PROTON_CALENDAR_FULL_NAME", "")
SMTP_HOST = os.environ.get("PROTON_CALENDAR_SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("PROTON_CALENDAR_SMTP_PORT", "1025"))
SMTP_USER = os.environ.get("PROTON_CALENDAR_SMTP_USER", "")
SMTP_TIMEOUT_SECONDS = 30
# The SMTP token is resolved lazily by credentials.get_smtp_password() (keyring
# first, PROTON_CALENDAR_SMTP_PASSWORD as fallback) so that importing this module
# never touches the keychain and a rotated Bridge token is picked up without a
# server restart.


def tool(fn: Callable[..., str]) -> Callable[..., str]:
    _TOOLS[fn.__name__] = (fn, TypeAdapter(fn))
    return fn


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [
        types.Tool(name=name, description=inspect.getdoc(fn), inputSchema=adapter.json_schema(), outputSchema=_OUTPUT_SCHEMA)
        for name, (fn, adapter) in _TOOLS.items()
    ]


@server.call_tool(validate_input=False)
async def _call_tool(name: str, arguments: dict[str, Any]):
    text = _TOOLS[name][1].validate_python(ArgsKwargs((), arguments))
    return [types.TextContent(type="text", text=text)], {"result": text}


def _generate_ics(method: str, uid: str, summary: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, **fields) -> str:
    """Build the ICS for one event, as this organizer, stamped now."""
    return build_ics(
        method=method,
        uid=uid,
        summary=summary,
        start=start_time,
        end=end_time,
        dtstamp=datetime.now(timezone.utc),
        organizer_email=EMAIL,
        organizer_name=FULL_NAME,
        **fields,
    )


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
    msg["Subject"] = re.sub(r"[\r\n]+", " ", subject)

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

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(SMTP_USER, smtp_password)
        server.sendmail(EMAIL, all_recipients, msg.as_bytes())


@tool
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
        all_day: Whether this is an all-day event (optional, default False). A later
            end_time at midnight is exclusive, as in RFC 5545; a same-day end, or one
            with a time of day, includes that date.
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


@tool
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
        all_day: Whether this is an all-day event (optional, default False). A later
            end_time at midnight is exclusive, as in RFC 5545; a same-day end, or one
            with a time of day, includes that date.
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


@tool
def cancel_proton_calendar_event(
    event_uid: str,
    summary: str,
    attendees: Optional[list[str]] = None,
) -> str:
    """Cancel an existing Proton Calendar event by sending a cancellation ICS.

    The user will need to open the email in Proton Mail to process the cancellation.

    Args:
        event_uid: The UID of the event to cancel (from create_proton_calendar_event)
        summary: The event title/summary (for the cancellation email subject)
        attendees: Email addresses to send the cancellation to, so invitees' copies are
            cancelled too (optional). Without them it goes to you only, and invitees
            keep the event.
    """
    ics_content = _generate_ics(
        method="CANCEL",
        uid=event_uid,
        summary=summary,
        status="CANCELLED",
        sequence=99,
        attendees=attendees,
    )

    _send_ics_email(
        f"Calendar Cancellation: {summary}",
        ics_content,
        method="CANCEL",
        recipients=attendees,
    )

    return (
        f"Event cancellation sent successfully.\n"
        f"UID: {event_uid}\n"
        f"Summary: {summary}\n"
        + (f"Attendees: {', '.join(attendees)}\n" if attendees else "")
    )


async def _serve() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    if not EMAIL:
        raise SystemExit("PROTON_CALENDAR_EMAIL is required: it is the organizer and always a recipient.")
    anyio.run(_serve)


if __name__ == "__main__":
    main()
