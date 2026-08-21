"""Tests for how the SMTP send path consumes the resolved credential."""

from __future__ import annotations

import pytest

from mcp_proton_calendar import app

FAKE_SECRET = "fake-bridge-token-for-tests"  # not a real credential


class FakeSMTP:
    """Minimal stand-in for ``smtplib.SMTP`` used as a context manager."""

    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sendmail_args: tuple[str, list[str], bytes] | None = None
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
        self.sendmail_args = (sender, recipients, message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    monkeypatch.setattr(app.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_send_uses_resolved_password(
    monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]
) -> None:
    monkeypatch.setattr(app, "get_smtp_password", lambda: FAKE_SECRET)

    app._send_ics_email("Calendar: Test", "BEGIN:VCALENDAR\r\nEND:VCALENDAR", method="PUBLISH")

    (server,) = fake_smtp.instances
    assert server.started_tls is True
    assert server.login_args == (app.SMTP_USER, FAKE_SECRET)
    assert server.sendmail_args is not None


def test_send_raises_helpful_error_without_credential(
    monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]
) -> None:
    monkeypatch.setattr(app, "get_smtp_password", lambda: "")

    with pytest.raises(RuntimeError, match="No Proton Bridge SMTP credential found"):
        app._send_ics_email("Calendar: Test", "BEGIN:VCALENDAR\r\nEND:VCALENDAR", method="PUBLISH")

    assert fake_smtp.instances == []
