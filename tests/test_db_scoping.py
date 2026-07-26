"""Tests for CR-2 — the per-transaction RLS scope.

The Postgres policies in migrations/001_rls_least_privilege.sql filter on a
transaction-local setting, ``app.user_email``. If the app ever stops publishing
it, every query silently returns nothing; if it publishes the wrong value, one
member sees another's trips. These tests pin the contract.

The suite runs on SQLite, which has no RLS, so the dialect-specific behaviour is
checked against a fake connection rather than a live Postgres.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import database as db  # noqa: E402


class _FakeDialect:
    def __init__(self, name):
        self.name = name


class _FakeConn:
    """Records what _apply_user_scope executes, without a database."""

    def __init__(self, dialect_name):
        self.dialect = _FakeDialect(dialect_name)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return None


@pytest.fixture
def as_user(monkeypatch):
    """Set the current user without needing a Streamlit session."""
    def _set(email):
        monkeypatch.setattr(db, "get_current_user", lambda: email)
    return _set


# ---- Postgres: the scope must be published, safely ------------------------

def test_postgres_publishes_the_current_user(as_user):
    as_user("angler@test.com")
    conn = _FakeConn("postgresql")
    db._apply_user_scope(conn)

    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "set_config" in sql
    assert "app.user_email" in sql
    assert params == {"email": "angler@test.com"}


def test_scope_is_transaction_local_not_session_wide(as_user):
    """is_local => true. A session-wide SET would leak across pooled checkouts."""
    as_user("angler@test.com")
    conn = _FakeConn("postgresql")
    db._apply_user_scope(conn)

    sql, _ = conn.calls[0]
    normalised = sql.lower().replace(" ", "")
    assert ",true)" in normalised, "set_config must pass is_local=true"


def test_email_is_bound_not_interpolated(as_user):
    """SET LOCAL cannot take bind params, which is why set_config is used.

    An email spliced into SQL would be an injection point on a value that,
    under OIDC, comes from an external identity provider.
    """
    hostile = "x'; DROP TABLE sessions; --"
    as_user(hostile)
    conn = _FakeConn("postgresql")
    db._apply_user_scope(conn)

    sql, params = conn.calls[0]
    assert hostile not in sql
    assert params == {"email": hostile}


def test_empty_user_still_publishes_and_therefore_denies(as_user):
    """No signed-in user must not mean 'no filter'.

    Publishing '' makes the policy compare against an address no row holds, so
    the query returns nothing. Skipping the call entirely would leave the
    setting at whatever the previous transaction used.
    """
    as_user("")
    conn = _FakeConn("postgresql")
    db._apply_user_scope(conn)

    assert len(conn.calls) == 1
    assert conn.calls[0][1] == {"email": ""}


# ---- SQLite: no RLS, so the call must be skipped, not attempted ----------

@pytest.mark.parametrize("dialect", ["sqlite", "mysql", "duckdb"])
def test_non_postgres_dialects_are_skipped(as_user, dialect):
    as_user("angler@test.com")
    conn = _FakeConn(dialect)
    db._apply_user_scope(conn)
    assert conn.calls == [], f"{dialect} has no set_config; calling it would error"


# ---- The context managers actually apply the scope -----------------------

def test_read_connection_applies_scope(monkeypatch, as_user):
    as_user("reader@test.com")
    seen = []
    monkeypatch.setattr(db, "_apply_user_scope", lambda c: seen.append(c))

    class _Engine:
        def connect(self):
            return _Ctx()

    class _Ctx:
        def __enter__(self):
            return "conn"

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(db, "get_engine", lambda: _Engine())

    with db.read_connection() as conn:
        assert conn == "conn"
    assert seen == ["conn"], "read_connection must scope before yielding"


def test_write_transaction_applies_scope(monkeypatch, as_user):
    as_user("writer@test.com")
    seen = []
    monkeypatch.setattr(db, "_apply_user_scope", lambda c: seen.append(c))

    class _Engine:
        def begin(self):
            return _Ctx()

    class _Ctx:
        def __enter__(self):
            return "conn"

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(db, "get_engine", lambda: _Engine())

    with db.write_transaction() as conn:
        assert conn == "conn"
    assert seen == ["conn"], "write_transaction must scope before yielding"
