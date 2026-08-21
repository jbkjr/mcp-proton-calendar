"""SMTP credential resolution.

The Proton Bridge SMTP token is looked up in the OS keyring first and only falls
back to the ``PROTON_CALENDAR_SMTP_PASSWORD`` environment variable, so the token
does not have to sit in plaintext inside an MCP client config file.

Resolution order:

1. The keyring entry named by ``PROTON_CALENDAR_KEYRING_SERVICE`` /
   ``PROTON_CALENDAR_KEYRING_USERNAME`` when either is set (that pair is then the
   *only* keyring entry consulted).
2. This server's own entry: service ``mcp-proton-calendar``, username ``smtp``.
3. The sibling mcp-email-server's entry for the same Bridge token: service
   ``mcp-email-server``, username ``proton:outgoing``. Bridge issues one token per
   account, so sharing that entry keeps one token in one place instead of two
   copies that drift apart when Bridge regenerates it.
4. The ``PROTON_CALENDAR_SMTP_PASSWORD`` environment variable.

Nothing here imports the mcp-email-server package; step 3 is just a
(service, username) string pair, overridable via the env vars in step 1.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PASSWORD_ENV_VAR = "PROTON_CALENDAR_SMTP_PASSWORD"
SERVICE_ENV_VAR = "PROTON_CALENDAR_KEYRING_SERVICE"
USERNAME_ENV_VAR = "PROTON_CALENDAR_KEYRING_USERNAME"

DEFAULT_KEYRING_SERVICE = "mcp-proton-calendar"
DEFAULT_KEYRING_USERNAME = "smtp"

# mcp-email-server stores account credentials as "{account_name}:{role}".
SHARED_KEYRING_SERVICE = "mcp-email-server"
SHARED_KEYRING_USERNAME = "proton:outgoing"


def keyring_candidates() -> list[tuple[str, str]]:
    """The (service, username) pairs to try, in order."""
    service = os.environ.get(SERVICE_ENV_VAR, "").strip()
    username = os.environ.get(USERNAME_ENV_VAR, "").strip()
    if service or username:
        return [(service or DEFAULT_KEYRING_SERVICE, username or DEFAULT_KEYRING_USERNAME)]
    return [
        (DEFAULT_KEYRING_SERVICE, DEFAULT_KEYRING_USERNAME),
        (SHARED_KEYRING_SERVICE, SHARED_KEYRING_USERNAME),
    ]


def _keyring_get(service: str, username: str) -> str | None:
    """Read one keyring entry, treating any backend failure as "not found"."""
    try:
        import keyring
    except ImportError:  # pragma: no cover - keyring is a declared dependency
        logger.debug("keyring is not installed; skipping keyring lookup")
        return None

    try:
        secret = keyring.get_password(service, username)
    except Exception as exc:
        # A locked keychain, a denied prompt, or a headless machine with no
        # usable backend all land here. Never fail the send over it; the
        # environment variable is still a valid source.
        logger.warning("Keyring lookup for %s/%s failed: %s", service, username, exc)
        return None

    return secret or None


def get_smtp_password() -> str:
    """Resolve the Proton Bridge SMTP token, or return "" if none is configured."""
    for service, username in keyring_candidates():
        secret = _keyring_get(service, username)
        if secret:
            logger.debug("Using SMTP credential from keyring entry %s/%s", service, username)
            return secret

    secret = os.environ.get(PASSWORD_ENV_VAR, "")
    if secret:
        logger.debug("Using SMTP credential from %s", PASSWORD_ENV_VAR)
    return secret


def describe_sources() -> str:
    """Human-readable list of the places consulted, for error messages."""
    entries = ", ".join(f"{service}/{username}" for service, username in keyring_candidates())
    return f"keyring entries ({entries}) and the {PASSWORD_ENV_VAR} environment variable"
