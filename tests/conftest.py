"""Shared fixtures: the real MCP server, an in-memory client and a fake SMTP."""

from __future__ import annotations

import email
from dataclasses import dataclass
from email.message import Message

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_proton_calendar import app

FAKE_SECRET = "fake-bridge-token-for-tests"  # not a real credential


@dataclass
class Sent:
    sender: str
    recipients: list[str]
    message: Message

    @property
    def ics(self) -> str:
        part = next(p for p in self.message.walk() if p.get_content_type() == "text/calendar")
        return part.get_payload(decode=True).decode("utf-8")


class FakeSMTP:
    """Stand-in for ``smtplib.SMTP`` used as a context manager."""

    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[Sent] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def sendmail(self, sender: str, recipients: list[str], message: bytes) -> None:
        self.sent.append(Sent(sender, recipients, email.message_from_bytes(message)))


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    monkeypatch.setattr(app.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]):
    """The configured server, ready for `call` and `list_tools`; never reaches a real keyring or SMTP."""
    monkeypatch.setattr(app, "EMAIL", "me@example.com")
    monkeypatch.setattr(app, "FULL_NAME", "Test Organizer")
    monkeypatch.setattr(app, "get_smtp_password", lambda: FAKE_SECRET)
    return app.mcp


def _with_session(fn):
    async def run():
        async with create_connected_server_and_client_session(app.mcp._mcp_server) as session:
            return await fn(session)

    return anyio.run(run)


def call(tool: str, **arguments: object):
    """Call a tool through an in-memory MCP client; returns the CallToolResult."""
    return _with_session(lambda s: s.call_tool(tool, arguments))


def list_tools():
    return _with_session(lambda s: s.list_tools()).tools


def last_sent(fake_smtp: type[FakeSMTP]) -> Sent:
    return fake_smtp.instances[-1].sent[-1]
