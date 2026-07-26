"""Tests for CR-4 — a trip is written whole or not at all.

A trip is an aggregate: the session row, its fish, and its route spots. These
used to be written in three separate transactions, so a mid-way failure
committed a partial trip. Editing was worse — it committed the DELETE of fish
and spots first and re-inserted afterwards, so a failure in between destroyed a
trip's catch data with nothing to put back.

Each test forces a failure at a specific step and asserts the database is
untouched. They run against the same in-memory SQLite engine as the rest of the
suite; SQLite honours transaction rollback, which is the property under test.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import data_entry, database as db  # noqa: E402

TEST_EMAIL = "angler@test.com"

_DDL = """
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    date TEXT, start_time TEXT, end_time TEXT, hours_fished REAL,
    location_name TEXT, latitude REAL, longitude REAL,
    weather TEXT, air_temp REAL, water_temp REAL,
    bait_lure TEXT, fishing_style TEXT,
    num_anglers INTEGER DEFAULT 1, dwr_filed INTEGER DEFAULT 0,
    dwr_filed_at TEXT,
    notes TEXT, moon_phase TEXT
);
CREATE TABLE fish (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    species TEXT, length REAL DEFAULT 0, weight REAL DEFAULT 0,
    kept INTEGER DEFAULT 0, depth REAL
);
CREATE TABLE spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    latitude REAL, longitude REAL, label TEXT, caught INTEGER DEFAULT 0,
    fish_count INTEGER
);
"""


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    from sqlalchemy import create_engine, event, text

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        for stmt in _DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt.strip()))

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_current_user", lambda: TEST_EMAIL)
    return engine


def _counts(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            for t in ("sessions", "fish", "spots")
        }


TRIP = {
    "date": "2026-07-04", "location_name": "SML — Main Channel",
    "num_anglers": 1, "hours_fished": 3.0,
}
FISH = [{"species": "Striper", "length": 24.0, "weight": 5.0}]
SPOTS = [{"lat": 37.16, "lon": -79.71, "label": "start"}]


class Boom(RuntimeError):
    """Stand-in for a database or network failure mid-write."""


# ---- Create -------------------------------------------------------------

def test_successful_add_writes_all_three(_db):
    data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))
    assert _counts(_db) == {"sessions": 1, "fish": 1, "spots": 1}


def test_fish_failure_leaves_no_session(_db, monkeypatch):
    """Acceptance: a forced fish insert failure leaves no newly created session."""
    monkeypatch.setattr(db, "insert_fish_tx",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("fish exploded")))

    with pytest.raises(data_entry.SaveError):
        data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))

    assert _counts(_db) == {"sessions": 0, "fish": 0, "spots": 0}


def test_spot_failure_leaves_no_session_or_fish(_db, monkeypatch):
    """Acceptance: a forced spot failure leaves no newly created session or fish."""
    monkeypatch.setattr(db, "insert_spots_tx",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("spots exploded")))

    with pytest.raises(data_entry.SaveError):
        data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))

    assert _counts(_db) == {"sessions": 0, "fish": 0, "spots": 0}


# ---- Edit ---------------------------------------------------------------

def test_edit_failure_preserves_original_session_fish_and_spots(_db, monkeypatch):
    """Acceptance: a forced edit failure preserves the original trip intact.

    This is the regression that mattered most — the old code committed the
    DELETEs before re-inserting, so this scenario used to end with the trip
    still present but stripped of every fish and spot.
    """
    sid = data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))
    before = _counts(_db)
    assert before == {"sessions": 1, "fish": 1, "spots": 1}

    monkeypatch.setattr(db, "insert_fish_tx",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("re-insert exploded")))

    edited = dict(TRIP)
    edited["location_name"] = "SOMEWHERE ELSE"
    with pytest.raises(data_entry.SaveError):
        data_entry.update_session(sid, edited,
                                  [{"species": "Catfish", "length": 30.0}],
                                  [{"lat": 38.0, "lon": -79.0}])

    assert _counts(_db) == before, "fish and spots must survive a failed edit"

    from sqlalchemy import text
    with _db.connect() as conn:
        row = conn.execute(
            text("SELECT location_name FROM sessions WHERE id = :i"), {"i": sid}
        ).mappings().first()
        species = conn.execute(
            text("SELECT species FROM fish WHERE session_id = :i"), {"i": sid}
        ).scalar()
    assert row["location_name"] == TRIP["location_name"], "the UPDATE must roll back too"
    assert species == "Striper", "the original fish must still be the original fish"


def test_successful_edit_replaces_children(_db):
    sid = data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))
    data_entry.update_session(sid, dict(TRIP),
                              [{"species": "Catfish", "length": 30.0},
                               {"species": "Muskie", "length": 40.0}],
                              [{"lat": 38.0, "lon": -79.0}])

    assert _counts(_db) == {"sessions": 1, "fish": 2, "spots": 1}


def test_edit_with_spots_none_leaves_the_route_alone(_db):
    sid = data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))
    data_entry.update_session(sid, dict(TRIP), list(FISH), None)
    assert _counts(_db)["spots"] == 1, "spots=None means 'do not touch the route'"


# ---- Error surface ------------------------------------------------------

def test_save_error_is_safe_to_show_a_user(_db, monkeypatch):
    """The message must not leak the driver, table names, or the raw exception."""
    monkeypatch.setattr(db, "insert_fish_tx",
                        lambda *a, **k: (_ for _ in ()).throw(
                            Boom("could not connect to host db.internal password=hunter2")))

    with pytest.raises(data_entry.SaveError) as caught:
        data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))

    message = str(caught.value)
    for leak in ("password", "hunter2", "db.internal", "Boom", "Traceback"):
        assert leak not in message, f"{leak!r} leaked into a user-facing message"
    assert caught.value.reference in message
    assert len(caught.value.reference) == 8


def test_each_failure_gets_its_own_reference(_db, monkeypatch):
    monkeypatch.setattr(db, "insert_fish_tx",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("x")))

    refs = set()
    for _ in range(3):
        with pytest.raises(data_entry.SaveError) as caught:
            data_entry.add_session(dict(TRIP), list(FISH), list(SPOTS))
        refs.add(caught.value.reference)
    assert len(refs) == 3, "references must be unique so logs can be told apart"


def test_validation_errors_are_not_swallowed_into_save_errors(_db):
    """A bad trip must still say what is wrong, not 'try again later'."""
    with pytest.raises(data_entry.ValidationError):
        data_entry.add_session({"date": "", "location_name": ""}, [], [])


def test_editing_a_missing_session_raises_validation_not_save_error(_db):
    with pytest.raises(data_entry.ValidationError):
        data_entry.update_session(9999, dict(TRIP), list(FISH), list(SPOTS))
