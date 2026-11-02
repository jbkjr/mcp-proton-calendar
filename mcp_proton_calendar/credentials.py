"""SMTP credential resolution: the OS keyring first, then an environment variable.

1. This server's own entry: service ``mcp-proton-calendar``, username ``smtp``.
2. mcp-email-server's entry for the same Bridge token: service ``mcp-email-server``,
   username ``proton:outgoing``, so one token lives in one place.
3. The ``PROTON_CALENDAR_SMTP_PASSWORD`` environment variable.
"""

from __future__ import annotations

import logging
import os

import keyring

logger = logging.getLogger(__name__)

PASSWORD_ENV_VAR = "PROTON_CALENDAR_SMTP_PASSWORD"
KEYRING_ENTRIES = [("mcp-proton-calendar", "smtp"), ("mcp-email-server", "proton:outgoing")]


def _keyring_get(service: str, username: str) -> str | None:
    """Read one entry. A locked keychain or missing backend counts as "not found", so the env var still works."""
    try:
        return keyring.get_password(service, username) or None
    except Exception as exc:
        logger.warning("Keyring lookup for %s/%s failed: %s", service, username, exc)
        return None


def get_smtp_password() -> str:
    """Resolve the Proton Bridge SMTP token, or return "" if none is configured."""
    for service, username in KEYRING_ENTRIES:
        secret = _keyring_get(service, username)
        if secret:
            return secret
    return os.environ.get(PASSWORD_ENV_VAR, "")


def describe_sources() -> str:
    """Human-readable list of the places consulted, for error messages."""
    entries = ", ".join(f"{service}/{username}" for service, username in KEYRING_ENTRIES)
    return f"keyring entries ({entries}) and the {PASSWORD_ENV_VAR} environment variable"
