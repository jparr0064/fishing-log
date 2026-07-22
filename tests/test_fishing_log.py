"""Tests for validation, data entry, search, and analytics against in-memory SQLite."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import analytics, data_entry, database as db, map_view, search  # noqa: E402

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
    """Each test gets a fresh in-memory SQLite engine scoped to TEST_EMAIL."""
    from sqlalchemy import create_engine, event, text

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_current_user", lambda: TEST_EMAIL)
    monkeypatch.setattr(db, "set_current_user", lambda e: None)
    yield
    engine.dispose()


# ---------------------------------------------------------------------------
# Pure-logic (no DB)
# ---------------------------------------------------------------------------

def test_compute_hours_basic():
    assert data_entry.compute_hours("06:00", "11:30") == 5.5


def test_compute_hours_crosses_midnight():
    assert data_entry.compute_hours("22:00", "01:00") == 3.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_latitude_rejected():
    with pytest.raises(data_entry.ValidationError):
        data_entry.add_session(
            {"date": "2025-05-01", "location_name": "X", "latitude": 200, "longitude": 0}, []
        )


def test_missing_date_rejected():
    with pytest.raises(data_entry.ValidationError):
        data_entry.add_session({"location_name": "X"}, [])


def test_negative_count_rejected():
    with pytest.raises(data_entry.ValidationError):
        data_entry.add_session(
            {"date": "2025-05-01", "location_name": "X"},
            [{"species": "Bass", "count": -2}],
        )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def test_add_session_autocomputes_hours():
    sid = data_entry.add_session(
        {"date": "2025-05-01", "start_time": "06:00", "end_time": "09:00",
         "location_name": "Test Lake", "latitude": 40.0, "longitude": -100.0,
         "weather": "Sunny"},
        [{"species": "Bass", "count": 3}],
    )
    detail = search.get_session(sid)
    assert detail["hours_fished"] == 3.0
    assert detail["total_fish"] == 3


def test_add_session_with_individual_fish():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [
            {"species": "Striper", "length": 24.5, "weight": 5.2},
            {"species": "Catfish", "length": 18, "weight": 0},
        ],
    )
    d = search.get_session(sid)
    assert d["total_fish"] == 2
    striper = next(f for f in d["fish"] if f["species"] == "Striper")
    assert striper["length"] == 24.5 and striper["weight"] == 5.2


def test_kept_and_anglers_roundtrip():
    sid = data_entry.add_session(
        {"date": "2026-06-25", "location_name": "SML", "num_anglers": 3},
        [{"species": "Striper", "length": 31, "weight": 10, "kept": True},
         {"species": "Striper", "length": 20, "weight": 3, "kept": False}],
    )
    d = search.get_session(sid)
    assert d["num_anglers"] == 3
    kept = [f for f in d["fish"] if f["kept"]]
    assert len(kept) == 1 and kept[0]["length"] == 31


def test_update_session_edits_fields_and_catches():
    sid = data_entry.add_session(
        {"date": "2026-06-01", "location_name": "SML", "weather": "Sunny",
         "bait_lure": "Worm", "fishing_style": "Casting"},
        [{"species": "Striper", "count": 3}],
    )
    assert search.get_session(sid)["fishing_style"] == "Casting"

    data_entry.update_session(
        sid,
        {"date": "2026-06-02", "location_name": "SML", "weather": "Rain",
         "bait_lure": "Spoon", "fishing_style": "Planer Boards"},
        [{"species": "Catfish", "count": 5}, {"species": "Muskie", "count": 1}],
    )
    d2 = search.get_session(sid)
    assert d2["date"] == "2026-06-02"
    assert d2["weather"] == "Rain"
    assert d2["fishing_style"] == "Planer Boards"
    assert d2["total_fish"] == 6
    assert {f["species"] for f in d2["fish"]} == {"Catfish", "Muskie"}


def test_update_session_replaces_spots_but_keeps_when_none():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7}],
    )
    # spots=None must NOT wipe existing spots
    data_entry.update_session(sid, {"date": "2026-06-07", "location_name": "SML"}, [])
    assert len(search.get_session(sid)["spots"]) == 1
    # passing a new list replaces them
    data_entry.update_session(
        sid, {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 38.0, "lon": -80.0}, {"lat": 38.1, "lon": -80.1}],
    )
    assert len(search.get_session(sid)["spots"]) == 2


def test_update_session_preserves_latlon_when_no_spots():
    """Editing a trip with an empty spot picker must not null its starting coords."""
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7}],
    )
    assert search.get_session(sid)["latitude"] == 37.1
    # Update with spots=[] (empty picker) and no lat/lon in the session dict
    data_entry.update_session(sid, {"date": "2026-06-08", "location_name": "SML"}, [], [])
    d = search.get_session(sid)
    assert d["date"] == "2026-06-08"          # other fields updated
    assert d["latitude"] == 37.1 and d["longitude"] == -79.7  # coords preserved


def test_delete_all_sessions():
    _seed_three()
    assert db.session_count() == 3
    removed = db.delete_all_sessions()
    assert removed == 3
    assert db.session_count() == 0
    assert search.list_sessions().empty


# ---------------------------------------------------------------------------
# Search / filtering
# ---------------------------------------------------------------------------

def _seed_three():
    data_entry.add_session(
        {"date": "2025-06-01", "location_name": "Alpha", "weather": "Sunny",
         "hours_fished": 4},
        [{"species": "Bass", "count": 5}],
    )
    data_entry.add_session(
        {"date": "2025-06-15", "location_name": "Alpha", "weather": "Rain",
         "hours_fished": 2},
        [],
    )
    data_entry.add_session(
        {"date": "2025-12-20", "location_name": "Beta", "weather": "Sunny",
         "hours_fished": 5},
        [{"species": "Pike", "count": 1}, {"species": "Bass", "count": 2}],
    )


def test_search_filters():
    _seed_three()
    assert len(search.list_sessions(location="Alpha")) == 2
    assert len(search.list_sessions(species="Pike")) == 1
    assert len(search.list_sessions(date_from="2025-12-01")) == 1


def test_search_total_fish_column():
    _seed_three()
    df = search.list_sessions(location="Beta")
    assert int(df.iloc[0]["total_fish"]) == 3


def test_baits_by_frequency_and_recent_defaults():
    data_entry.add_session(
        {"date": "2025-06-01", "location_name": "L", "bait_lure": "Worm", "weather": "Sunny"}, []
    )
    data_entry.add_session(
        {"date": "2025-06-02", "location_name": "L", "bait_lure": "Worm", "weather": "Rain"}, []
    )
    data_entry.add_session(
        {"date": "2025-06-03", "location_name": "L", "bait_lure": "Jig", "weather": "Cloudy"}, []
    )
    assert search.baits_by_frequency()[0] == "Worm"
    rd = search.recent_defaults()
    assert rd["bait_lure"] == "Jig"
    assert rd["weather"] == "Cloudy"


# ---------------------------------------------------------------------------
# Spots
# ---------------------------------------------------------------------------

def test_add_session_with_spots_and_map_rows():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [{"species": "Striper", "length": 20, "weight": 4}],
        [{"lat": 37.1, "lon": -79.7}, {"lat": 37.2, "lon": -79.8}],
    )
    d = search.get_session(sid)
    assert len(d["spots"]) == 2
    assert d["latitude"] == 37.1 and d["longitude"] == -79.7

    rows = search.map_rows()
    assert len(rows) == 1
    assert rows.iloc[0]["latitude"] == 37.1
    assert int(rows.iloc[0]["total_fish"]) == 1


def test_spot_caught_flag_roundtrip_and_route_map():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7, "caught": False},
         {"lat": 37.15, "lon": -79.72, "caught": True}],
    )
    spots = search.get_session(sid)["spots"]
    assert [bool(s["caught"]) for s in spots] == [False, True]

    pts = [{"lat": s["latitude"], "lon": s["longitude"], "caught": bool(s["caught"])} for s in spots]
    html = map_view.build_route_map(pts)._repr_html_().lower()
    assert "antpath" in html
    assert "ud83d" in html  # 🐟 JSON-escaped


def test_spot_fish_count_roundtrip_and_badge():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7, "fish_count": 0},
         {"lat": 37.15, "lon": -79.72, "fish_count": 10}],
    )
    spots = search.get_session(sid)["spots"]
    assert [s["fish_count"] for s in spots] == [0, 10]
    # A positive count implies caught; zero does not.
    assert [bool(s["caught"]) for s in spots] == [False, True]

    pts = [{"lat": s["latitude"], "lon": s["longitude"],
            "caught": bool(s["caught"]), "fish_count": s["fish_count"]} for s in spots]
    html = map_view.build_route_map(pts)._repr_html_().lower()
    assert "times;10" in html          # ×10 badge rendered
    assert "10 fish caught" in html    # tooltip includes the count


def test_spot_fish_count_optional_and_validated():
    # Legacy shape (no count) still works and stores NULL.
    sid = data_entry.add_session(
        {"date": "2026-06-08", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7, "caught": True}],
    )
    s = search.get_session(sid)["spots"][0]
    assert s["fish_count"] is None and bool(s["caught"])

    with pytest.raises(data_entry.ValidationError):
        data_entry.validate_spots([{"lat": 37.1, "lon": -79.7, "fish_count": -1}])


def test_caught_spot_points():
    data_entry.add_session(
        {"date": "2026-06-25", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7, "caught": True},
         {"lat": 37.2, "lon": -79.8, "caught": False}],
    )
    assert search.caught_spot_points() == [[37.1, -79.7]]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def test_analytics_success_rate_by_location():
    _seed_three()
    by_loc = analytics.by_location().set_index("location_name")
    assert by_loc.loc["Alpha", "success_rate_%"] == 50.0
    assert by_loc.loc["Beta", "success_rate_%"] == 100.0


def test_analytics_by_species_totals():
    _seed_three()
    by_sp = analytics.by_species().set_index("species")
    assert int(by_sp.loc["Bass", "total_caught"]) == 7
    assert int(by_sp.loc["Bass", "sessions_present"]) == 2


def test_overall_stats():
    _seed_three()
    stats = analytics.overall_stats()
    assert stats["sessions"] == 3
    assert stats["total_fish"] == 8
    assert stats["success_rate"] == pytest.approx(66.7, abs=0.1)


def test_by_month_fills_all_twelve():
    data_entry.add_session(
        {"date": "2026-06-01", "location_name": "SML", "hours_fished": 3},
        [{"species": "Striper", "count": 5}],
    )
    data_entry.add_session(
        {"date": "2026-06-15", "location_name": "SML", "hours_fished": 2}, []
    )
    data_entry.add_session(
        {"date": "2026-08-01", "location_name": "SML", "hours_fished": 4},
        [{"species": "Catfish", "count": 2}],
    )
    df = analytics.by_month(2026)
    assert len(df) == 12
    by_m = df.set_index("month")
    assert int(by_m.loc["June", "total_fish"]) == 5
    assert int(by_m.loc["June", "sessions"]) == 2
    assert by_m.loc["June", "success_rate_%"] == 50.0
    assert int(by_m.loc["August", "total_fish"]) == 2
    assert int(by_m.loc["January", "sessions"]) == 0
    assert by_m.loc["January", "success_rate_%"] == 0.0


def test_available_years_desc():
    data_entry.add_session({"date": "2025-06-01", "location_name": "SML"}, [])
    data_entry.add_session({"date": "2026-06-01", "location_name": "SML"}, [])
    assert analytics.available_years() == [2026, 2025]


def test_by_species_size_metrics():
    data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [
            {"species": "Striper", "length": 20, "weight": 4},
            {"species": "Striper", "length": 30, "weight": 6},
        ],
    )
    bysp = analytics.by_species().set_index("species")
    assert int(bysp.loc["Striper", "total_caught"]) == 2
    assert bysp.loc["Striper", "avg_length"] == 25.0
    assert bysp.loc["Striper", "max_length"] == 30
    assert bysp.loc["Striper", "avg_weight"] == 5.0


def test_personal_bests():
    data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [{"species": "Striper", "length": 20, "weight": 4},
         {"species": "Striper", "length": 31, "weight": 9}],
    )
    data_entry.add_session(
        {"date": "2026-06-14", "location_name": "SML"},
        [{"species": "Catfish", "length": 25, "weight": 6}],
    )
    pb = analytics.personal_bests().set_index("species")
    assert pb.loc["Striper", "longest_in"] == 31.0
    assert pb.loc["Striper", "heaviest_lb"] == 9.0
    assert pb.loc["Striper", "longest_date"] == "2026-06-07"
    assert pb.loc["Catfish", "longest_in"] == 25.0


def test_size_by_month():
    data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [{"species": "Striper", "length": 20, "weight": 4},
         {"species": "Striper", "length": 30, "weight": 6}],
    )
    sm = analytics.size_by_month(2026).set_index("month")
    assert len(sm) == 12
    assert sm.loc["June", "avg_length"] == 25.0
    assert sm.loc["June", "max_length"] == 30.0
    assert int(sm.loc["June", "fish"]) == 2
    assert int(sm.loc["January", "fish"]) == 0


def test_condition_insights():
    data_entry.add_session(
        {"date": "2026-06-01", "location_name": "SML", "water_temp": 62,
         "fishing_style": "Planer Boards", "start_time": "06:00", "hours_fished": 4},
        [{"species": "Striper", "length": 30, "weight": 8}],
    )
    data_entry.add_session(
        {"date": "2026-06-08", "location_name": "SML", "water_temp": 48,
         "fishing_style": "Casting", "start_time": "13:00", "hours_fished": 3}, [],
    )
    wt = analytics.by_water_temp().set_index("water_band")
    assert wt.loc[analytics._water_band(62), "success_rate_%"] == 100.0
    assert wt.loc[analytics._water_band(48), "success_rate_%"] == 0.0

    tod = analytics.by_time_of_day().set_index("tod")
    assert int(tod.loc[analytics._tod_band("06:00"), "sessions"]) == 1

    assert not analytics.by_fishing_style().empty
    bests = analytics.best_conditions(min_sessions=1)
    assert any(fph > 0 for _, _, fph in bests)


# ---------------------------------------------------------------------------
# DWR report
# ---------------------------------------------------------------------------

def test_dwr_summarize_and_url():
    from fishing_log import dwr_report
    session = {
        "date": "2026-06-25", "hours_fished": 4.0, "num_anglers": 2,
        "fish": [
            {"species": "Striper", "length": 31, "weight": 10, "kept": True},
            {"species": "Striper", "length": 28, "weight": 8, "kept": True},
            {"species": "Striper", "length": 20.5, "weight": 3, "kept": False},
            {"species": "Catfish", "length": 18, "weight": 2, "kept": True},  # excluded
        ],
    }
    r = dwr_report.summarize(session)
    assert r["harvested_n"] == 2
    assert r["harvested_sizes"] == '31", 28"'
    assert r["released_n"] == 1
    assert r["released_sizes"] == '20.5"'
    assert r["anglers"] == 2 and r["hours"] == "4"

    url = dwr_report.prefilled_url(session)
    # emailAddress is no longer prefilled — each angler's Google account supplies it
    assert "emailAddress" not in url
    assert "entry.1950519841=2" in url   # harvested count
    assert "entry.19977333=1" in url     # released count
    assert "entry.841781509=2" in url    # anglers
    assert "entry.210458085_year=2026" in url
    assert "entry.210458085_month=6" in url and "entry.210458085_day=25" in url


def test_dwr_harvested_na_when_zero():
    from fishing_log import dwr_report
    session = {
        "date": "2026-06-25", "hours_fished": 4, "num_anglers": 1,
        "fish": [{"species": "Striper", "length": 26, "weight": 5, "kept": False}],
    }
    r = dwr_report.summarize(session)
    assert r["harvested_n"] == 0
    assert r["harvested_sizes"] == "N/A"
    assert r["released_sizes"] == '26"'


def test_dwr_sizes_fallback_when_unmeasured():
    """A striper logged without a length must never leave the sizes field blank
    while its count is prefilled (looks like the prefill half-failed)."""
    from fishing_log import dwr_report
    session = {
        "date": "2026-07-01", "num_anglers": 1,
        "fish": [
            {"species": "Striper", "length": 0, "weight": 0, "kept": False},
            {"species": "Striper", "length": 0, "weight": 0, "kept": True},
        ],
    }
    r = dwr_report.summarize(session)
    assert r["released_n"] == 1 and r["released_sizes"] == "Not measured"
    assert r["harvested_n"] == 1 and r["harvested_sizes"] == "Not measured"
    url = dwr_report.prefilled_url(session)
    assert "Not+measured" in url


def test_dwr_filed_roundtrip():
    sid = data_entry.add_session({"date": "2026-06-25", "location_name": "SML"}, [])
    assert search.get_session(sid)["dwr_filed"] == 0
    data_entry.set_dwr_filed(sid, True)
    assert search.get_session(sid)["dwr_filed"] == 1
    data_entry.set_dwr_filed(sid, False)
    assert search.get_session(sid)["dwr_filed"] == 0


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def test_map_success_tiers():
    assert map_view._tier(0)[0] == "Skunked"
    assert map_view._tier(1)[0] == "Good"
    assert map_view._tier(3)[0] == "Good"
    assert map_view._tier(4)[0] == "Great"
    assert map_view._tier(6)[0] == "Great"
    assert map_view._tier(7)[0] == "Blowout"
    assert map_view._tier(25)[0] == "Blowout"


# ---------------------------------------------------------------------------
# Write scoping (IDOR fix verification)
# ---------------------------------------------------------------------------

def test_write_scoping():
    """update/delete/set_dwr_filed must not affect another user's sessions."""
    from sqlalchemy import text

    engine = db.get_engine()
    # Insert a session directly as another user (bypassing get_current_user)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO sessions (user_email, date, location_name, num_anglers, dwr_filed, moon_phase) "
            "VALUES ('other@test.com', '2026-06-01', 'SML', 1, 0, 'Waxing Crescent')"
        ))
        other_sid = conn.execute(text("SELECT last_insert_rowid()")).scalar()

    # update_session as TEST_EMAIL: no matching row → ValidationError
    with pytest.raises(data_entry.ValidationError):
        data_entry.update_session(other_sid, {"date": "2026-06-01", "location_name": "SML"}, [])

    # delete_session as TEST_EMAIL: silently a no-op
    data_entry.delete_session(other_sid)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM sessions WHERE id = :id"), {"id": other_sid}).scalar()
    assert n == 1, "Other user's session must not be deleted"

    # set_dwr_filed as TEST_EMAIL: returns 0 (no rows touched)
    n_updated = data_entry.set_dwr_filed(other_sid, True)
    assert n_updated == 0
