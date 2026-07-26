"""Tests for CR-5 — bounded query load and per-user cache isolation.

The Analytics page derives a dozen summaries from two datasets. Each summary
used to run its own query, so one render meant a dozen round trips for
identical data. These pin the two properties that matter: the base frames are
fetched once per cache generation, and one angler's cached frame can never be
handed to another.
"""
from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import analytics, backup_io, data_entry, database as db  # noqa: E402

EMAIL_A = "angler.a@test.com"
EMAIL_B = "angler.b@test.com"

_DDL = """
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    date TEXT, start_time TEXT, end_time TEXT, hours_fished REAL,
    location_name TEXT, latitude REAL, longitude REAL,
    weather TEXT, air_temp REAL, water_temp REAL,
    bait_lure TEXT, fishing_style TEXT,
    num_anglers INTEGER DEFAULT 1, dwr_filed INTEGER DEFAULT 0,
    dwr_filed_at TEXT, notes TEXT, moon_phase TEXT, trip_uuid TEXT
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


class _User:
    """Mutable current-user holder so a test can switch anglers."""

    def __init__(self, email):
        self.email = email

    def __call__(self):
        return self.email


@pytest.fixture
def env(monkeypatch):
    from sqlalchemy import create_engine, event, text

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        for stmt in _DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt.strip()))

    user = _User(EMAIL_A)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_current_user", user)
    return engine, user


def _log_trip(date="2026-07-04", fish=1, **extra):
    session = {"date": date, "location_name": "SML", "num_anglers": 1,
               "hours_fished": 3.0, "weather": "Sunny", "water_temp": 62,
               "fishing_style": "Downlines", "start_time": "06:00"}
    session.update(extra)
    return data_entry.add_session(
        session,
        [{"species": "Striper", "length": 24.0, "weight": 5.0}] * fish,
        [],
    )


# ---- The base frames are loaded once, not once per summary ---------------

def test_many_summaries_share_one_session_query(env, monkeypatch):
    _log_trip()

    calls = []
    real = analytics._load_session_frame
    monkeypatch.setattr(analytics, "_load_session_frame",
                        lambda: (calls.append(1), real())[1])
    analytics._session_frame_cached.clear()

    # Everything the Analytics page and hero banner touch in one render.
    analytics.overall_stats()
    analytics.available_years()
    analytics.by_month(2026)
    analytics.by_weather()
    analytics.by_water_temp()
    analytics.by_time_of_day()
    analytics.by_fishing_style()
    analytics.by_bait()
    analytics.by_moon_phase()
    analytics.year_over_year()
    analytics.by_location()

    assert len(calls) == 1, (
        f"11 summaries triggered {len(calls)} session queries; they must share one"
    )


def test_fish_summaries_share_one_query(env, monkeypatch):
    _log_trip()

    calls = []
    real = analytics._load_fish_with_dates
    monkeypatch.setattr(analytics, "_load_fish_with_dates",
                        lambda: (calls.append(1), real())[1])
    analytics._fish_frame_cached.clear()

    analytics.personal_bests()
    analytics.size_by_month(2026)
    analytics.fish_sizes(2026)
    analytics.overall_stats()

    assert len(calls) == 1


def test_a_whole_analytics_render_stays_under_five_round_trips(env, monkeypatch):
    """CR-5 acceptance: no more than five DB round trips per read-only render."""
    _log_trip()

    from sqlalchemy import event
    engine, _ = env
    statements = []

    def _count(conn, cursor, statement, *a):
        # Ignore the transaction-scope statement; it is not a data query.
        if "set_config" not in statement.lower():
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        analytics._session_frame_cached.clear()
        analytics._fish_frame_cached.clear()
        analytics.overall_stats()
        analytics.by_month(2026)
        analytics.personal_bests()
        analytics.size_by_month(2026)
        analytics.by_weather()
        analytics.year_over_year()
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(statements) <= 5, (
        f"{len(statements)} round trips for one analytics render: {statements}"
    )


# ---- Cache isolation between users --------------------------------------

def test_one_users_cached_frame_is_never_served_to_another(env):
    engine, user = env

    user.email = EMAIL_A
    _log_trip(fish=3)
    a_stats = analytics.overall_stats()

    user.email = EMAIL_B
    b_stats = analytics.overall_stats()

    assert a_stats["sessions"] == 1
    assert b_stats["sessions"] == 0, "angler B must not see angler A's cached trips"

    user.email = EMAIL_B
    _log_trip(fish=7, date="2026-07-05")
    assert analytics.overall_stats()["sessions"] == 1

    user.email = EMAIL_A
    assert analytics.overall_stats()["sessions"] == 1, "A's own data must be intact"


def test_cache_invalidates_after_that_users_write(env):
    _log_trip()
    assert analytics.overall_stats()["sessions"] == 1

    _log_trip(date="2026-07-05")
    assert analytics.overall_stats()["sessions"] == 2, (
        "a committed write must invalidate the cached frame"
    )


def test_one_users_write_does_not_invalidate_only_by_luck(env):
    """B writing must not make A re-query — but A must still be correct."""
    engine, user = env

    user.email = EMAIL_A
    _log_trip()
    assert analytics.overall_stats()["sessions"] == 1

    user.email = EMAIL_B
    _log_trip(date="2026-07-06")

    user.email = EMAIL_A
    assert analytics.overall_stats()["sessions"] == 1


# ---- Backup builds without querying anything twice -----------------------

def test_building_the_zip_reads_each_table_once(env):
    _log_trip()
    engine, _ = env

    from sqlalchemy import event
    reads = []

    def _count(conn, cursor, statement, *a):
        low = statement.lower()
        if low.strip().startswith("select") and "set_config" not in low:
            for table in ("from sessions", "from fish", "from spots"):
                if table in low:
                    reads.append(table)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        payload = backup_io.build_zip_bytes()
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert reads.count("from sessions") == 1, f"sessions read {reads.count('from sessions')}x"
    assert len(reads) == 3, f"expected one read per table, got {reads}"

    # And the ZIP is still complete.
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert set(zf.namelist()) == {
            "sessions.csv", "fish.csv", "spots.csv", backup_io.JSON_NAME}


def test_export_backup_accepts_prefetched_frames(env):
    _log_trip()
    sessions, fish, spots = (
        backup_io._sessions_df(), backup_io._fish_df(), backup_io._spots_df())
    data = backup_io.export_backup(sessions, fish, spots)
    assert data["session_count"] == 1
    assert data["sessions"][0]["fish"], "prefetched frames must still populate children"
