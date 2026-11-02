"""Tests for SMTP credential resolution (keyring first, env var fallback).

Every test runs against a fake ``keyring`` module, so the suite never reads the
real OS keychain and never handles a real credential.
"""

from __future__ import annotations

import pytest

from mcp_proton_calendar import credentials

FAKE_SECRET = "fake-bridge-token-for-tests"  # not a real credential
OWN_ENTRY = ("mcp-proton-calendar", "smtp")
SHARED_ENTRY = ("mcp-email-server", "proton:outgoing")  # must move together with mcp-email-server


class FakeKeyring:
    """Stand-in for the ``keyring`` module backed by an in-memory dict."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str | None] = {}
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append((service, username))
        if self.error is not None:
            raise self.error
        return self.store.get((service, username))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from the developer's own environment."""
    monkeypatch.delenv(credentials.PASSWORD_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """Replace the ``keyring`` module so the real keychain is never touched."""
    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "keyring", fake)
    return fake


def test_uses_own_keyring_entry(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[OWN_ENTRY] = FAKE_SECRET

    assert credentials.get_smtp_password() == FAKE_SECRET
    assert fake_keyring.calls == [OWN_ENTRY]


def test_falls_back_to_shared_email_server_entry(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[SHARED_ENTRY] = FAKE_SECRET

    assert credentials.get_smtp_password() == FAKE_SECRET
    assert fake_keyring.calls == [OWN_ENTRY, SHARED_ENTRY]


def test_own_entry_wins_over_shared_entry(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[OWN_ENTRY] = FAKE_SECRET
    fake_keyring.store[SHARED_ENTRY] = "other-value"

    assert credentials.get_smtp_password() == FAKE_SECRET


def test_env_var_used_when_no_keyring_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(credentials.PASSWORD_ENV_VAR, FAKE_SECRET)

    assert credentials.get_smtp_password() == FAKE_SECRET


def test_keyring_entry_wins_over_env_var(
    monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    monkeypatch.setenv(credentials.PASSWORD_ENV_VAR, "stale-env-value")
    fake_keyring.store[OWN_ENTRY] = FAKE_SECRET

    assert credentials.get_smtp_password() == FAKE_SECRET


def test_keyring_backend_error_falls_back_to_env_var(
    monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    fake_keyring.error = RuntimeError("keychain is locked")
    monkeypatch.setenv(credentials.PASSWORD_ENV_VAR, FAKE_SECRET)

    assert credentials.get_smtp_password() == FAKE_SECRET


def test_empty_keyring_value_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    fake_keyring.store[OWN_ENTRY] = ""
    fake_keyring.store[SHARED_ENTRY] = ""
    monkeypatch.setenv(credentials.PASSWORD_ENV_VAR, FAKE_SECRET)

    assert credentials.get_smtp_password() == FAKE_SECRET


def test_returns_empty_string_when_nothing_is_configured() -> None:
    assert credentials.get_smtp_password() == ""


def test_override_env_vars_are_ignored(
    monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    monkeypatch.setenv("PROTON_CALENDAR_KEYRING_SERVICE", "custom-service")
    monkeypatch.setenv("PROTON_CALENDAR_KEYRING_USERNAME", "custom-user")
    fake_keyring.store[SHARED_ENTRY] = FAKE_SECRET

    assert credentials.get_smtp_password() == FAKE_SECRET
    assert fake_keyring.calls == [OWN_ENTRY, SHARED_ENTRY]


def test_describe_sources_lists_entries_and_env_var() -> None:
    description = credentials.describe_sources()

    assert "mcp-proton-calendar/smtp" in description
    assert "mcp-email-server/proton:outgoing" in description
    assert credentials.PASSWORD_ENV_VAR in description
