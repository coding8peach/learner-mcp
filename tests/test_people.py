"""People: passcodes, email fingerprints, sign-in, and removing someone.

The pure checks always run; the database ones need TEST_DATABASE_URL
(a throwaway Postgres), like tests/test_repository.py.
"""
import os
import uuid

import pytest

from learner_mcp import people as P

TEST_DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")


@pytest.fixture(autouse=True)
def email_key(monkeypatch):
    monkeypatch.setenv("LEARNER_EMAIL_KEY", "k" * 32)


def test_passcode_is_forgiving_and_salted():
    h = P.hash_passcode("Maple Otter 42")
    assert P.check_passcode("maple-otter-42", h)
    assert not P.check_passcode("maple otter 43", h)
    assert P.hash_passcode("maple otter 42") != h          # different salt each time


def test_short_passcode_rejected():
    with pytest.raises(ValueError, match="too short"):
        P.hash_passcode("ab 1")


def test_email_fingerprint_is_keyed_and_normalized(monkeypatch):
    fp = P.email_fingerprint("  KK@Example.com ")
    assert fp == P.email_fingerprint("kk@example.com")
    assert "example" not in fp and len(fp) == 64
    monkeypatch.setenv("LEARNER_EMAIL_KEY", "z" * 32)
    assert P.email_fingerprint("kk@example.com") != fp    # useless without the key


def test_email_needs_key_and_valid_address(monkeypatch):
    with pytest.raises(ValueError, match="email address"):
        P.email_fingerprint("not-an-email")
    monkeypatch.setenv("LEARNER_EMAIL_KEY", "")
    with pytest.raises(ValueError, match="LEARNER_EMAIL_KEY"):
        P.email_fingerprint("kk@example.com")


def test_bad_usernames():
    for bad in ("", "a", "Has Space", "-dash", "x" * 40):
        with pytest.raises(ValueError):
            P._username(bad)
    assert P._username(" KK ") == "kk"


# ---------------- database ----------------

@pytest.fixture(scope="module")
def db():
    os.environ["DATABASE_URL"] = TEST_DB
    return P


def _name():
    return "t" + uuid.uuid4().hex[:10]


@needs_db
def test_add_sign_in_update(db):
    u = _name()
    p = db.add_person(u, "Tester", "student", passcode="maple otter 42", email=f"{u}@example.com")
    assert p.has_passcode and p.has_email and p.role == "student" and p.active
    assert db.sign_in(u.upper(), "Maple-Otter 42").username == u
    for user, code in ((u, "wrong passcode"), ("nobody-" + u[:5], "maple otter 42")):
        with pytest.raises(ValueError, match="Wrong user name or passcode"):
            db.sign_in(user, code)
    assert db.find_person_by_email(f"{u.upper()}@EXAMPLE.com").username == u
    assert db.find_person_by_email("someone.else@example.com") is None

    db.update_person(u, active=False)
    with pytest.raises(ValueError, match="Wrong"):
        db.sign_in(u, "maple otter 42")                   # inactive can't sign in
    db.update_person(u, active=True, passcode="river stone 7", email="")
    assert db.sign_in(u, "river stone 7") and not db.get_person(u).has_email


@needs_db
def test_duplicates_rejected(db):
    u, v = _name(), _name()
    db.add_person(u, email=f"{u}@example.com", passcode="maple otter 42")
    with pytest.raises(ValueError, match="taken"):
        db.add_person(u)
    with pytest.raises(ValueError, match="already belongs"):
        db.add_person(v, email=f"{u}@example.com")


@needs_db
def test_import_existing_hash(db):
    u = _name()
    old = P.hash_passcode("old code 99")
    db.add_person(u, passcode_hash=old)
    assert db.sign_in(u, "old code 99")
    with pytest.raises(ValueError, match="pbkdf2"):
        db.add_person(_name(), passcode_hash="plaintext")


@needs_db
def test_keep_one_parent(db):
    # make this test's parent the only active one
    for other in db.list_people():
        if other.role == "parent" and other.active:
            db.update_person(other.username, active=False)
    a, b = _name(), _name()
    db.add_person(a, role="parent", passcode="maple otter 42")
    with pytest.raises(ValueError, match="at least one active parent"):
        db.update_person(a, role="student")
    with pytest.raises(ValueError, match="at least one active parent"):
        db.delete_person(a)
    db.add_person(b, role="parent", passcode="maple otter 42")
    db.update_person(a, role="student")                  # fine now: b is a parent


@needs_db
def test_delete_erases_history(db):
    from learner_mcp import repository as repo
    from learner_mcp.models import AttemptIn
    u = _name()
    db.add_person(u, passcode="maple otter 42")
    repo.record_attempt(AttemptIn(student=u, subject="sat-rw", item_ref="sat:x", reasoning="missed"), "test")
    out = db.delete_person(u)
    assert out["attempts_deleted"] == 1
    assert db.get_person(u) is None
    assert repo.list_attempts(u) == []
