"""People who can sign in to the apps: added by a parent, no self sign-up.

Privacy by design:
  - passcodes are stored only as salted PBKDF2 hashes
  - emails are never stored: only a keyed fingerprint (HMAC-SHA256 with
    LEARNER_EMAIL_KEY), enough to recognize an email again (e.g. a Google
    Form answer) but not to read it back
  - progress is filed under the user name (a nickname), not a real name
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

from psycopg.rows import dict_row

from learner_mcp.database import get_connection
from learner_mcp.models import Person

ITERATIONS = 200_000
MIN_PASSCODE = 6
ROLES = ("student", "parent")
USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WRONG = "Wrong user name or passcode."

_COLUMNS = ("username, display_name, role, active, passcode_hash is not null as has_passcode, "
            "email_fp is not null as has_email, created_at, last_sign_in")


# ---------------- passcodes & email fingerprints ----------------

def normalize_passcode(passcode: str) -> str:
    """Forgiving: 'Maple-Otter River 42' -> 'mapleotterriver42'"""
    return re.sub(r"[^a-z0-9]", "", (passcode or "").lower())


def hash_passcode(passcode: str) -> str:
    p = normalize_passcode(passcode)
    if len(p) < MIN_PASSCODE:
        raise ValueError(f"Passcode is too short: use at least {MIN_PASSCODE} letters or digits, "
                         "e.g. 'maple otter 42'.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt}${digest.hex()}"


def check_passcode(passcode: str, stored: str | None) -> bool:
    try:
        _, iterations, salt, digest = (stored or "").split("$")
        test = hashlib.pbkdf2_hmac("sha256", normalize_passcode(passcode).encode(),
                                   bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, TypeError):
        return False


_DUMMY = None


def _dummy_hash() -> str:
    """Checked when the user name doesn't exist, so a wrong name takes as
    long as a wrong passcode (no hint which one was wrong)."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_passcode("not-a-real-passcode")
    return _DUMMY


def email_fingerprint(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL.match(email):
        raise ValueError(f"That doesn't look like an email address: {email!r}")
    key = os.getenv("LEARNER_EMAIL_KEY", "").strip()
    if len(key) < 24:
        raise ValueError("LEARNER_EMAIL_KEY is not set on the learner-mcp server (at least 24 random "
                         "characters; make one with scripts/new_api_key.py). Emails can't be used until it is.")
    return hmac.new(key.encode(), email.encode(), hashlib.sha256).hexdigest()


# ---------------- helpers ----------------

def _username(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME.match(u):
        raise ValueError("User name must be 2-32 characters: lowercase letters, digits, '.', '_' or '-', "
                         "starting with a letter or digit (e.g. 'kk', 'alex.p').")
    return u


def _role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    return role


def _person(row: dict) -> Person:
    return Person(**row)


def _active_parents(cur, excluding: str | None = None) -> int:
    cur.execute("select count(*) as n from learner.people where role = 'parent' and active "
                "and (%s::text is null or username <> %s)", (excluding, excluding))
    return cur.fetchone()["n"]


# ---------------- people ----------------

def add_person(username: str, display_name: str | None = None, role: str = "student",
               passcode: str | None = None, email: str | None = None,
               passcode_hash: str | None = None) -> Person:
    username, role = _username(username), _role(role)
    if passcode and passcode_hash:
        raise ValueError("Give a passcode or a passcode_hash, not both.")
    if passcode_hash and not passcode_hash.startswith("pbkdf2$"):
        raise ValueError("passcode_hash must be a pbkdf2$... hash (e.g. from an app's old passcode list).")
    stored = hash_passcode(passcode) if passcode else passcode_hash
    fp = email_fingerprint(email) if email else None
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select 1 from learner.people where username = %s", (username,))
        if cur.fetchone():
            raise ValueError(f"User name {username!r} is taken.")
        if fp:
            cur.execute("select username from learner.people where email_fp = %s", (fp,))
            if (other := cur.fetchone()):
                raise ValueError(f"That email already belongs to {other['username']!r}.")
        cur.execute(
            f"""insert into learner.people (username, display_name, role, passcode_hash, email_fp)
                values (%s, %s, %s, %s, %s) returning {_COLUMNS}""",
            (username, (display_name or "").strip() or None, role, stored, fp),
        )
        return _person(cur.fetchone())


def update_person(username: str, display_name: str | None = None, role: str | None = None,
                  active: bool | None = None, passcode: str | None = None,
                  email: str | None = None) -> Person:
    """None leaves a field as it is. email="" removes the email."""
    username = _username(username)
    sets, args = [], []
    if display_name is not None:
        sets.append("display_name = %s"); args.append(display_name.strip() or None)
    if role is not None:
        sets.append("role = %s"); args.append(_role(role))
    if active is not None:
        sets.append("active = %s"); args.append(bool(active))
    if passcode is not None:
        sets.append("passcode_hash = %s"); args.append(hash_passcode(passcode))
    fp = None
    if email is not None:
        fp = email_fingerprint(email) if email.strip() else None
        sets.append("email_fp = %s"); args.append(fp)
    if not sets:
        raise ValueError("Nothing to change.")
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select {_COLUMNS} from learner.people where username = %s for update", (username,))
        current = cur.fetchone()
        if not current:
            raise ValueError(f"No one with user name {username!r}.")
        stops_parent = current["role"] == "parent" and current["active"] and (
            (role is not None and role != "parent") or active is False)
        if stops_parent and _active_parents(cur, excluding=username) == 0:
            raise ValueError("Keep at least one active parent, or no one could manage people.")
        if fp:
            cur.execute("select username from learner.people where email_fp = %s and username <> %s",
                        (fp, username))
            if (other := cur.fetchone()):
                raise ValueError(f"That email already belongs to {other['username']!r}.")
        cur.execute(f"update learner.people set {', '.join(sets)}, updated_at = now() "
                    f"where username = %s returning {_COLUMNS}", (*args, username))
        return _person(cur.fetchone())


def list_people(include_inactive: bool = True) -> list[Person]:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select {_COLUMNS} from learner.people where %s or active "
                    "order by role desc, username", (include_inactive,))
        return [_person(r) for r in cur.fetchall()]


def get_person(username: str) -> Person | None:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select {_COLUMNS} from learner.people where username = %s",
                    ((username or "").strip().lower(),))
        row = cur.fetchone()
        return _person(row) if row else None


def sign_in(username: str, passcode: str) -> Person:
    """The person if the user name and passcode match an active account.
    Every failure gives the same message."""
    u = (username or "").strip().lower()
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select passcode_hash, active from learner.people where username = %s", (u,))
        row = cur.fetchone()
        ok = check_passcode(passcode, row["passcode_hash"] if row else _dummy_hash())
        if not (row and ok and row["active"]):
            raise ValueError(WRONG)
        cur.execute(f"update learner.people set last_sign_in = now() where username = %s "
                    f"returning {_COLUMNS}", (u,))
        return _person(cur.fetchone())


def find_person_by_email(email: str) -> Person | None:
    fp = email_fingerprint(email)
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select {_COLUMNS} from learner.people where email_fp = %s", (fp,))
        row = cur.fetchone()
        return _person(row) if row else None


def delete_person(username: str, delete_history: bool = True) -> dict:
    """Remove someone. With delete_history (the default), also erase every
    attempt and test sitting saved under their user name."""
    username = _username(username)
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select {_COLUMNS} from learner.people where username = %s for update", (username,))
        current = cur.fetchone()
        if not current:
            raise ValueError(f"No one with user name {username!r}.")
        if current["role"] == "parent" and current["active"] and _active_parents(cur, excluding=username) == 0:
            raise ValueError("Keep at least one active parent, or no one could manage people.")
        attempts = sessions = 0
        if delete_history:
            cur.execute("delete from learner.attempts where student = %s", (username,))
            attempts = cur.rowcount
            cur.execute("delete from learner.test_sessions where student = %s", (username,))
            sessions = cur.rowcount
        cur.execute("delete from learner.people where username = %s", (username,))
        return {"username": username, "attempts_deleted": attempts, "test_sittings_deleted": sessions}
