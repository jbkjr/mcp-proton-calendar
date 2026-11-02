"""Tests for how the SMTP send path consumes the resolved credential."""

from __future__ import annotations

import pytest

from conftest import FAKE_SECRET, FakeSMTP

from mcp_proton_calendar import app


def test_send_uses_resolved_password(
    monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]
) -> None:
    monkeypatch.setattr(app, "get_smtp_password", lambda: FAKE_SECRET)

    app._send_ics_email("Calendar: Test", "BEGIN:VCALENDAR\r\nEND:VCALENDAR", method="PUBLISH")

    (server,) = fake_smtp.instances
    assert server.started_tls is True
    assert server.login_args == (app.SMTP_USER, FAKE_SECRET)
    assert server.sent


def test_send_raises_helpful_error_without_credential(
    monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]
) -> None:
    monkeypatch.setattr(app, "get_smtp_password", lambda: "")

    with pytest.raises(RuntimeError, match="No Proton Bridge SMTP credential found"):
        app._send_ics_email("Calendar: Test", "BEGIN:VCALENDAR\r\nEND:VCALENDAR", method="PUBLISH")

    assert fake_smtp.instances == []


def test_smtp_connection_has_a_timeout(
    monkeypatch: pytest.MonkeyPatch, fake_smtp: type[FakeSMTP]
) -> None:
    monkeypatch.setattr(app, "get_smtp_password", lambda: FAKE_SECRET)

    app._send_ics_email("Calendar: Test", "BEGIN:VCALENDAR\r\nEND:VCALENDAR", method="PUBLISH")

    assert fake_smtp.instances[0].timeout == app.SMTP_TIMEOUT_SECONDS > 0
