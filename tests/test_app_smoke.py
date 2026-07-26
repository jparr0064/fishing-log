"""Tests for CR-6 — app-level smoke tests across the auth and data states.

Everything else in this suite tests the package. These drive the real app.py
through streamlit.testing.v1.AppTest, which is the only coverage of the parts
that have historically broken in production: which page renders for which auth
state, and whether a page raises at all.

Two hard rules:

* **Never point at the production database.** Each test gets its own temporary
  SQLite file via DATABASE_URL, seeded with the app's schema.
* **Never execute the destructive path.** The "Clear my data" gating is tested
  by asserting the button is disabled — the delete itself is covered by the
  package tests against an in-memory database.

Interactive components (st_folium, streamlit_geolocation) render as
UnknownElement under AppTest; that is expected and does not fail a run.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

OWNER = "owner@test.com"
APPROVED = "member@test.com"
DEMO = "demo@fishinglog.demo"

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

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="AppTest unavailable"
).AppTest


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    """A throwaway SQLite database. Never production — see module docstring."""
    from sqlalchemy import create_engine, text

    path = tmp_path / "smoke.db"
    url = f"sqlite:///{path}"

    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in _DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt.strip()))
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", url)
    # app.py caches its engine in a module global and st.cache_resource; make
    # sure a previous test's engine is not reused against a new file.
    from fishing_log import database as db
    db._engine = None
    db._trip_uuid_support.clear()
    yield url
    db._engine = None


def _seed(url, email, trips=2):
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as conn:
        for i in range(trips):
            conn.execute(
                text("INSERT INTO sessions "
                     "(user_email, date, location_name, num_anglers, "
                     " hours_fished, weather, trip_uuid) "
                     "VALUES (:e, :d, 'SML — Main Channel', 1, 3.0, 'Sunny', :u)"),
                {"e": email, "d": f"2026-07-{i + 1:02d}", "u": str(uuid.uuid4())},
            )
            sid = conn.execute(text("SELECT MAX(id) FROM sessions")).scalar()
            conn.execute(
                text("INSERT INTO fish (session_id, species, length, weight) "
                     "VALUES (:s, 'Striper', 24.0, 5.0)"),
                {"s": sid},
            )
    engine.dispose()


def _app(db_url, *, user=None, app_env="development", auth_mode="local",
         allowed=(APPROVED,)):
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["database_url"] = db_url
    at.secrets["dev_user_email"] = OWNER
    at.secrets["allowed_emails"] = list(allowed)
    at.secrets["app_env"] = app_env
    at.secrets["auth_mode"] = auth_mode
    if user is not None:
        at.session_state["user_email"] = user
    return at


def _text(at) -> str:
    """All rendered text, whatever element type carried it."""
    parts = []
    for group in (at.markdown, at.caption, at.header, at.subheader, at.title,
                  at.info, at.warning, at.error, at.success):
        try:
            parts.extend(str(e.value) for e in group)
        except Exception:
            pass
    return "\n".join(parts)


def _assert_no_exception(at):
    assert not at.exception, (
        "app raised: " + "; ".join(str(e.value) for e in at.exception))


# ---- Public / signed out ------------------------------------------------

def test_public_visitor_sees_the_login_page_and_no_data(db_url):
    _seed(db_url, APPROVED)
    at = _app(db_url).run()

    _assert_no_exception(at)
    body = _text(at)
    assert "Fishing Log" in body
    assert "Enter your email" in body
    assert "Dashboard" not in body, "a signed-out visitor must not reach a page"


def test_misconfigured_production_shows_maintenance_not_a_form(db_url):
    """CR-1's headline case, exercised through the real app."""
    at = _app(db_url, app_env="production", auth_mode="oidc").run()

    _assert_no_exception(at)
    body = _text(at)
    assert "temporarily unavailable" in body
    assert "Enter your email" not in body, "production must never offer the form"


def test_production_cannot_be_talked_into_local_auth(db_url):
    at = _app(db_url, app_env="production", auth_mode="local").run()
    _assert_no_exception(at)
    assert "Enter your email" not in _text(at)


# ---- Demo ---------------------------------------------------------------

def test_demo_renders_read_only(db_url):
    _seed(db_url, DEMO, trips=3)
    at = _app(db_url, user=DEMO).run()

    _assert_no_exception(at)
    body = _text(at)
    assert "Demo mode" in body and "read only" in body.lower()


def test_demo_cannot_reach_the_log_a_session_form(db_url):
    _seed(db_url, DEMO)
    at = _app(db_url, user=DEMO)
    at.run()
    at.sidebar.radio[0].set_value("Log a Session").run()

    _assert_no_exception(at)
    assert "read-only demo" in _text(at)


# ---- Signed-in accounts -------------------------------------------------

def test_empty_account_renders_without_charting_nothing(db_url):
    """The empty state used to be where Vega extent warnings came from."""
    at = _app(db_url, user=APPROVED).run()

    _assert_no_exception(at)
    assert "No sessions yet" in _text(at) or "No trips yet" in _text(at)


def test_populated_account_shows_its_own_totals(db_url):
    _seed(db_url, APPROVED, trips=4)
    at = _app(db_url, user=APPROVED).run()

    _assert_no_exception(at)
    values = [m.value for m in at.metric]
    assert "4" in values, f"expected 4 trips among metrics: {values}"


def test_one_members_trips_never_appear_for_another(db_url):
    _seed(db_url, "someone.else@test.com", trips=5)
    at = _app(db_url, user=APPROVED).run()

    _assert_no_exception(at)
    body = _text(at)
    assert "No sessions yet" in body or "No trips yet" in body, (
        "an empty account must not inherit another member's trips")


# ---- Every page renders -------------------------------------------------

@pytest.mark.parametrize("page", [
    "Dashboard", "Log a Session", "Browse & Search", "Analytics",
    "Calendar", "Map", "Export", "Privacy & Data",
])
def test_every_page_renders_for_a_signed_in_member(db_url, page):
    _seed(db_url, APPROVED, trips=2)
    at = _app(db_url, user=APPROVED)
    at.run()
    at.sidebar.radio[0].set_value(page).run()
    _assert_no_exception(at)


def test_privacy_page_states_there_is_no_server_side_backup(db_url):
    at = _app(db_url, user=APPROVED)
    at.run()
    at.sidebar.radio[0].set_value("Privacy & Data").run()

    _assert_no_exception(at)
    body = _text(at)
    assert "no server-side backup" in body.lower()
    assert "exact" in body.lower(), "must disclose exact-coordinate storage"


# ---- Destructive path is gated, never executed --------------------------

def test_clear_my_data_is_gated_behind_downloading_a_backup(db_url):
    """Asserts the gate, and never presses the button.

    The delete itself is covered against an in-memory database in the package
    tests; running it here would be a destructive probe for no extra signal.
    """
    _seed(db_url, APPROVED, trips=2)
    at = _app(db_url, user=APPROVED).run()
    _assert_no_exception(at)

    delete_buttons = [b for b in at.sidebar.button
                      if "Delete all my data" in str(b.label)]
    assert delete_buttons, "the clear-data control should be present"
    assert delete_buttons[0].disabled, (
        "delete must start disabled until a backup has been downloaded")

    from sqlalchemy import create_engine, text
    engine = create_engine(db_url)
    with engine.connect() as conn:
        remaining = conn.execute(text("SELECT COUNT(*) FROM sessions")).scalar()
    engine.dispose()
    assert remaining == 2, "rendering the page must not delete anything"


def test_demo_is_not_offered_the_clear_data_control(db_url):
    _seed(db_url, DEMO)
    at = _app(db_url, user=DEMO).run()
    _assert_no_exception(at)
    assert not [b for b in at.sidebar.button
                if "Delete all my data" in str(b.label)]
