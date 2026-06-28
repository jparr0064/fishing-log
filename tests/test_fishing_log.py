"""Tests for validation, data entry, search, and analytics against in-memory DB."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import analytics, data_entry, database as db, map_view, search  # noqa: E402


@pytest.fixture(autouse=True)
def memory_db():
    """Point every test at a fresh in-memory database."""
    db.set_db_path(":memory:")
    # A single shared connection is needed so :memory: persists across calls.
    conn = db.get_connection()
    db.init_db(conn)

    # Monkeypatch get_connection to reuse this one connection (no close).
    class _Keep:
        def __init__(self, c):
            self._c = c

        def __getattr__(self, name):
            return getattr(self._c, name)

        def close(self):  # ignore closes so the in-memory DB survives
            pass

    keeper = _Keep(conn)
    original = db.get_connection
    db.get_connection = lambda: keeper
    yield
    db.get_connection = original
    conn.close()
    db.set_db_path(db.DEFAULT_DB_PATH)


def test_compute_hours_basic():
    assert data_entry.compute_hours("06:00", "11:30") == 5.5


def test_compute_hours_crosses_midnight():
    assert data_entry.compute_hours("22:00", "01:00") == 3.0


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


def _seed_three():
    data_entry.add_session(
        {"date": "2025-06-01", "location_name": "Alpha", "weather": "Sunny",
         "hours_fished": 4},
        [{"species": "Bass", "count": 5}],
    )
    data_entry.add_session(
        {"date": "2025-06-15", "location_name": "Alpha", "weather": "Rain",
         "hours_fished": 2},
        [],  # skunked
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


def test_analytics_success_rate_by_location():
    _seed_three()
    by_loc = analytics.by_location().set_index("location_name")
    # Alpha: 2 sessions, 1 with fish -> 50%
    assert by_loc.loc["Alpha", "success_rate_%"] == 50.0
    assert by_loc.loc["Beta", "success_rate_%"] == 100.0


def test_analytics_by_species_totals():
    _seed_three()
    by_sp = analytics.by_species().set_index("species")
    assert int(by_sp.loc["Bass", "total_caught"]) == 7  # 5 + 2
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
    assert len(df) == 12  # all months present
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


def test_save_pil_images(monkeypatch):
    import shutil
    from PIL import Image
    from fishing_log import media

    test_dir = db.PROJECT_ROOT / "_test_photos"
    monkeypatch.setattr(db, "PHOTOS_DIR", test_dir)
    try:
        sid = data_entry.add_session({"date": "2026-06-01", "location_name": "SML"}, [])
        img = Image.new("RGB", (12, 8), "red")
        paths = media.save_pil_images(sid, [img], captions=["nice striper"])
        assert len(paths) == 1
        assert (db.PROJECT_ROOT / paths[0]).exists()
        photos = media.get_photos(sid)
        assert len(photos) == 1
        assert photos[0]["caption"] == "nice striper"
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_migration_adds_column_preserving_data():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Simulate an OLD database that predates the fishing_style column.
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, date TEXT, "
        "location_name TEXT, bait_lure TEXT)"
    )
    conn.execute(
        "INSERT INTO sessions (date, location_name, bait_lure) "
        "VALUES ('2025-01-01', 'SML', 'Worm')"
    )
    conn.commit()

    db._ensure_columns(conn)
    conn.commit()

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "fishing_style" in cols  # column added
    row = conn.execute("SELECT * FROM sessions").fetchone()
    assert row["location_name"] == "SML"  # existing data preserved
    assert row["bait_lure"] == "Worm"
    assert row["fishing_style"] is None
    conn.close()


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


def test_backfill_expands_catches_once():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # OLD-style DB: aggregate catches, no fish table, user_version 0.
    conn.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, date TEXT, location_name TEXT);
        CREATE TABLE catches (id INTEGER PRIMARY KEY, session_id INTEGER, species TEXT, count INTEGER);
        INSERT INTO sessions (id, date, location_name) VALUES (1, '2026-06-07', 'SML');
        INSERT INTO catches (session_id, species, count) VALUES (1, 'Striper', 3);
        """
    )
    conn.commit()

    db.init_db(conn)  # creates fish table + backfills 3 individual fish
    assert conn.execute("SELECT COUNT(*) AS n FROM fish").fetchone()["n"] == 3
    db.init_db(conn)  # version guard => no duplication
    assert conn.execute("SELECT COUNT(*) AS n FROM fish").fetchone()["n"] == 3
    row = conn.execute("SELECT species, length, weight FROM fish LIMIT 1").fetchone()
    assert row["species"] == "Striper" and row["length"] == 0 and row["weight"] == 0
    conn.close()


def test_exif_orientation_applied(tmp_path):
    from PIL import Image
    from fishing_log import media

    img = Image.new("RGB", (100, 50), "red")  # landscape
    exif = img.getexif()
    exif[274] = 6  # Orientation tag: rotate 90° CW when displaying
    p = tmp_path / "o.jpg"
    img.save(p, exif=exif)

    out = media.load_image_oriented(str(p))
    assert out.size == (50, 100)  # transposed to portrait — EXIF honored


def test_delete_photo_removes_row_and_file(monkeypatch):
    import shutil
    from PIL import Image
    from fishing_log import media

    test_dir = db.PROJECT_ROOT / "_test_photos2"
    monkeypatch.setattr(db, "PHOTOS_DIR", test_dir)
    try:
        sid = data_entry.add_session({"date": "2026-06-07", "location_name": "SML"}, [])
        media.save_pil_images(sid, [Image.new("RGB", (10, 10), "red")])
        photos = media.get_photos(sid)
        assert len(photos) == 1
        pid = photos[0]["id"]
        abs_path = photos[0]["abs_path"]
        assert os.path.exists(abs_path)

        media.delete_photo(pid)
        assert media.get_photos(sid) == []
        assert not os.path.exists(abs_path)
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_add_session_with_spots_and_map_rows():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"},
        [{"species": "Striper", "length": 20, "weight": 4}],
        [{"lat": 37.1, "lon": -79.7}, {"lat": 37.2, "lon": -79.8}],
    )
    d = search.get_session(sid)
    assert len(d["spots"]) == 2
    # Primary coordinate set from the first spot.
    assert d["latitude"] == 37.1 and d["longitude"] == -79.7

    rows = search.map_rows()
    assert len(rows) == 1  # overview map shows one starting dot per session
    assert rows.iloc[0]["latitude"] == 37.1  # the starting spot
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
    assert "antpath" in html  # directional route line present
    assert "ud83d" in html  # fish icon (🐟, JSON-escaped) marks the caught spot


def test_update_session_replaces_spots_but_keeps_when_none():
    sid = data_entry.add_session(
        {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7}],
    )
    # Passing spots=None must NOT wipe existing spots.
    data_entry.update_session(sid, {"date": "2026-06-07", "location_name": "SML"}, [])
    assert len(search.get_session(sid)["spots"]) == 1
    # Passing a new list replaces them.
    data_entry.update_session(
        sid, {"date": "2026-06-07", "location_name": "SML"}, [],
        [{"lat": 38.0, "lon": -80.0}, {"lat": 38.1, "lon": -80.1}],
    )
    assert len(search.get_session(sid)["spots"]) == 2


def test_spots_backfill_from_sessions():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, date TEXT, location_name TEXT,
                               latitude REAL, longitude REAL);
        INSERT INTO sessions (id, date, location_name, latitude, longitude)
        VALUES (1, '2026-06-07', 'SML', 37.1, -79.7);
        PRAGMA user_version = 1;
        """
    )
    conn.commit()

    db.init_db(conn)  # v2 migration seeds spots from the session coordinate
    rows = conn.execute("SELECT session_id, latitude FROM spots").fetchall()
    assert len(rows) == 1 and rows[0]["latitude"] == 37.1
    db.init_db(conn)  # idempotent
    assert conn.execute("SELECT COUNT(*) AS n FROM spots").fetchone()["n"] == 1
    conn.close()


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


def test_backup_create_and_prune(tmp_path, monkeypatch):
    import sqlite3
    from fishing_log import backup

    dbfile = tmp_path / "f.db"
    sqlite3.connect(dbfile).close()
    monkeypatch.setattr(db, "_db_path", dbfile)
    bdir = tmp_path / "backups"
    monkeypatch.setattr(backup, "BACKUP_DIR", bdir)

    created = backup.auto_backup()
    assert created is not None and created.exists()
    assert len(backup.list_backups()) >= 1

    # Prune keeps only the newest N.
    for i in range(15):
        (bdir / f"fishing_log-202601{i:02d}-000000.db").write_text("x")
    backup._prune(10)
    names = [p.name for p in backup.list_backups()]
    assert len(names) == 10
    assert "fishing_log-20260114-000000.db" in names  # newest kept


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
    assert "emailAddress=jcal0064%40gmail.com" in url  # email prefilled
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


def test_dwr_filed_roundtrip():
    sid = data_entry.add_session({"date": "2026-06-25", "location_name": "SML"}, [])
    assert search.get_session(sid)["dwr_filed"] == 0
    data_entry.set_dwr_filed(sid, True)
    assert search.get_session(sid)["dwr_filed"] == 1
    data_entry.set_dwr_filed(sid, False)
    assert search.get_session(sid)["dwr_filed"] == 0


def test_caught_spot_points():
    data_entry.add_session(
        {"date": "2026-06-25", "location_name": "SML"}, [],
        [{"lat": 37.1, "lon": -79.7, "caught": True},
         {"lat": 37.2, "lon": -79.8, "caught": False}],
    )
    assert search.caught_spot_points() == [[37.1, -79.7]]


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


def test_map_success_tiers():
    assert map_view._tier(0)[0] == "Skunked"
    assert map_view._tier(1)[0] == "Good"
    assert map_view._tier(3)[0] == "Good"
    assert map_view._tier(4)[0] == "Great"
    assert map_view._tier(6)[0] == "Great"
    assert map_view._tier(7)[0] == "Blowout"
    assert map_view._tier(25)[0] == "Blowout"


def test_delete_all_sessions():
    _seed_three()
    assert db.session_count() == 3
    removed = db.delete_all_sessions()
    assert removed == 3
    assert db.session_count() == 0
    assert search.list_sessions().empty


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
    # "Worm" used twice -> should rank first.
    assert search.baits_by_frequency()[0] == "Worm"
    # Most recent session is 2025-06-03 with Jig / Cloudy.
    rd = search.recent_defaults()
    assert rd["bait_lure"] == "Jig"
    assert rd["weather"] == "Cloudy"


def test_insert_photo_row_cascades_on_delete():
    sid = data_entry.add_session(
        {"date": "2025-06-01", "location_name": "L"}, []
    )
    conn = db.get_connection()
    db.insert_photo(conn, sid, "data/photos/x/abc.jpg", "nice bass")
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS n FROM photos WHERE session_id = ?", (sid,)).fetchone()["n"]
    assert n == 1
    data_entry.delete_session(sid)
    n2 = conn.execute("SELECT COUNT(*) AS n FROM photos").fetchone()["n"]
    assert n2 == 0
