"""Contact addresses, encrypted at rest.

The fingerprint in people.email_fp is for *recognizing* an email (a Google
Form answer). Apps that need to *send* email (Bellringer) also need the
address itself, so it is kept in people.email_enc, encrypted with
LEARNER_CONTACT_KEY. The key lives only in learner-mcp's environment, never
in the database, so a leaked database or backup shows only scrambled text.

Settings (learner-mcp's environment):
    LEARNER_CONTACT_KEY    one key, or several comma-separated for rotation:
                           the first encrypts, any of them decrypts.
                           Make one: uv run python -m learner_mcp.contacts
    LEARNER_CONTACT_APPS   app names (from LEARNER_MCP_API_KEYS) allowed to
                           read addresses, e.g. "bellringer". Default: none.

If the key isn't set, emails still get a fingerprint as before; the
address just isn't kept, and has_contact stays false.
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger("learner_mcp.contacts")
PREFIX = "v1:"      # format version, so the scheme can change later without guessing


def _clean(value: str) -> str:
    return (value or "").strip().strip("\"'").strip()


def _cipher() -> MultiFernet | None:
    raw = _clean(os.getenv("LEARNER_CONTACT_KEY", ""))
    if raw.startswith("LEARNER_CONTACT_KEY="):             # pasted with the name
        raw = raw.split("=", 1)[1]
    keys = [_clean(k) for k in raw.split(",") if _clean(k)]
    if not keys:
        return None
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            "LEARNER_CONTACT_KEY is not a valid key. Make one with: "
            "uv run python -m learner_mcp.contacts") from e


def enabled() -> bool:
    return _cipher() is not None


def encrypt(email: str) -> str | None:
    """Encrypted address, or None when no key is configured."""
    cipher = _cipher()
    if cipher is None:
        return None
    return PREFIX + cipher.encrypt(email.encode()).decode()


def decrypt(token: str) -> str:
    cipher = _cipher()
    if cipher is None:
        raise RuntimeError("LEARNER_CONTACT_KEY is not set on the learner-mcp server, "
                           "so stored addresses can't be read.")
    if not token.startswith(PREFIX):
        raise ValueError("Unknown contact format.")
    try:
        return cipher.decrypt(token[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise ValueError("This address was saved with a different key.") from e


def rotate(token: str) -> str:
    """Re-encrypt with the newest key (first in LEARNER_CONTACT_KEY)."""
    return PREFIX + _cipher().rotate(token[len(PREFIX):].encode()).decode()


def allowed_apps() -> set[str]:
    return {_clean(a) for a in os.getenv("LEARNER_CONTACT_APPS", "").split(",") if _clean(a)}


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
