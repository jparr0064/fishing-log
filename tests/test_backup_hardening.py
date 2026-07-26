"""Tests for CR-7 — bounded, versioned, idempotent, preview-first restore.

An uploaded backup is untrusted input, and restore is the one operation that
can silently double an angler's history with no server-side undo. These cover
the six CR-7 requirements: format versions, size and row limits, preview before
write, stable ids, per-trip atomicity, and CSV formula neutralisation.
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fishing_log import backup_io, data_entry, database as db  # noqa: E402

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
    notes TEXT, moon_phase TEXT,
    trip_uuid TEXT
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

    db._trip_uuid_support.clear()
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_current_user", lambda: TEST_EMAIL)
    yield engine
    db._trip_uuid_support.clear()


def _trip(date="2026-07-04", location="SML — Main Channel", uuid=None, **extra):
    rec = {
        "trip_uuid": uuid,
        "date": date, "start_time": "06:00", "end_time": "09:00",
        "hours_fished": 3.0, "location_name": location,
        "latitude": 37.16, "longitude": -79.71,
        "num_anglers": 1, "dwr_filed": 0,
        "fish": [{"species": "Striper", "length": 24.0, "weight": 5.0, "kept": False}],
        "spots": [{"lat": 37.16, "lon": -79.71, "caught": True}],
    }
    rec.update(extra)
    return rec


def _backup(sessions, version=backup_io.BACKUP_VERSION):
    return {
        "format": "fishing-log-backup",
        "version": version,
        "exported_at": "2026-07-26",
        "sessions": sessions,
    }


def _counts(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                for t in ("sessions", "fish", "spots")}


# ---- 1. Format versions are enforced ------------------------------------

def test_current_version_is_accepted():
    data = backup_io.parse_backup(json.dumps(_backup([_trip()])).encode())
    assert data["version"] == backup_io.BACKUP_VERSION


def test_previous_version_still_restores():
    """v1 files predate trip_uuid but must remain readable."""
    data = backup_io.parse_backup(json.dumps(_backup([_trip()], version=1)).encode())
    assert data["version"] == 1


def test_future_version_is_refused_with_an_actionable_message():
    raw = json.dumps(_backup([_trip()], version=backup_io.BACKUP_VERSION + 5)).encode()
    with pytest.raises(backup_io.BackupError) as caught:
        backup_io.parse_backup(raw)
    assert "Update the app" in str(caught.value)


@pytest.mark.parametrize("version", [None, 0, -1, "2", "latest", 1.5])
def test_unrecognised_versions_are_refused(version):
    raw = json.dumps(_backup([_trip()], version=version)).encode()
    with pytest.raises(backup_io.BackupError):
        backup_io.parse_backup(raw)


def test_a_non_backup_json_file_is_refused():
    with pytest.raises(backup_io.BackupError):
        backup_io.parse_backup(json.dumps({"hello": "world"}).encode())


# ---- 2. Size and row limits ---------------------------------------------

def test_oversized_upload_is_refused_before_parsing():
    raw = b"x" * (backup_io.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(backup_io.BackupError) as caught:
        backup_io.parse_backup(raw)
    assert "limit" in str(caught.value)


def test_empty_upload_is_refused():
    with pytest.raises(backup_io.BackupError):
        backup_io.parse_backup(b"")


def test_zip_bomb_is_refused_without_being_fully_decompressed():
    """A highly compressible member must not be expanded into memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # ~80 MB of zeros compresses to a few KB.
        zf.writestr(backup_io.JSON_NAME, b"\0" * (80 * 1024 * 1024))
    payload = buf.getvalue()
    assert len(payload) < backup_io.MAX_UPLOAD_BYTES, "repro should be small on disk"

    with pytest.raises(backup_io.BackupError) as caught:
        backup_io.parse_backup(payload)
    assert "too large" in str(caught.value) or "expands" in str(caught.value)


def test_too_many_sessions_is_refused():
    raw = json.dumps(_backup([_trip()] * (backup_io.MAX_SESSIONS + 1))).encode()
    with pytest.raises(backup_io.BackupError) as caught:
        backup_io.parse_backup(raw)
    assert "limit" in str(caught.value)


def test_too_many_children_on_one_trip_is_refused():
    fat = _trip(fish=[{"species": "Striper"}] * (backup_io.MAX_CHILDREN_PER_SESSION + 1))
    with pytest.raises(backup_io.BackupError) as caught:
        backup_io.parse_backup(json.dumps(_backup([fat])).encode())
    assert "limit" in str(caught.value)


def test_zip_without_backup_json_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sessions.csv", "a,b\n1,2\n")
    with pytest.raises(backup_io.BackupError):
        backup_io.parse_backup(buf.getvalue())


# ---- 3. Preview writes nothing ------------------------------------------

def test_preview_does_not_touch_the_database(_db):
    data = _backup([_trip(), _trip(date="2026-07-05")])
    before = _counts(_db)
    plan = backup_io.preview_restore(data)
    assert _counts(_db) == before, "preview must be read-only"
    assert plan["total"] == 2 and plan["to_restore"] == 2


def test_preview_counts_match_what_restore_does(_db):
    data = _backup([_trip(uuid="u1"), _trip(uuid="u2", date="2026-07-05")])
    plan = backup_io.preview_restore(data)
    result = backup_io.restore_backup(data)
    assert plan["to_restore"] == result["restored"]
    assert plan["duplicates"] == result["skipped"]


def test_preview_reports_duplicates_against_existing_trips(_db):
    data = _backup([_trip(uuid="u1")])
    backup_io.restore_backup(data)

    plan = backup_io.preview_restore(_backup([_trip(uuid="u1"), _trip(uuid="u2", date="2026-08-01")]))
    assert plan["duplicates"] == 1
    assert plan["to_restore"] == 1
    assert "uuid" in plan["matched_by"]


def test_preview_warns_when_a_backup_has_no_stable_ids(_db):
    plan = backup_io.preview_restore(_backup([_trip(uuid=None)]))
    assert any("no stable id" in w for w in plan["warnings"])


# ---- 4. Stable ids make restore idempotent ------------------------------

def test_restoring_the_same_backup_twice_adds_nothing_the_second_time(_db):
    data = _backup([_trip(uuid="u1"), _trip(uuid="u2", date="2026-07-05")])

    first = backup_io.restore_backup(data)
    after_first = _counts(_db)
    second = backup_io.restore_backup(data)

    assert first["restored"] == 2
    assert second["restored"] == 0 and second["skipped"] == 2
    assert _counts(_db) == after_first, "a second restore must be a no-op"


def test_uuid_beats_the_heuristic_when_a_trip_was_renamed(_db):
    """Editing a trip's location must not make it look like a new trip."""
    from sqlalchemy import text
    backup_io.restore_backup(_backup([_trip(uuid="u1")]))
    with _db.begin() as conn:
        conn.execute(text("UPDATE sessions SET location_name = 'Renamed Cove'"))

    result = backup_io.restore_backup(_backup([_trip(uuid="u1")]))
    assert result["skipped"] == 1, "same trip_uuid means same trip"
    assert _counts(_db)["sessions"] == 1


def test_v1_backup_without_uuids_falls_back_to_the_heuristic(_db):
    data = _backup([_trip(uuid=None)], version=1)
    backup_io.restore_backup(data)
    again = backup_io.restore_backup(data)
    assert again["skipped"] == 1
    assert _counts(_db)["sessions"] == 1


def test_new_trips_get_a_uuid_when_the_column_exists(_db):
    from sqlalchemy import text
    data_entry.add_session(
        {"date": "2026-07-04", "location_name": "SML", "num_anglers": 1}, [], [])
    with _db.connect() as conn:
        uid = conn.execute(text("SELECT trip_uuid FROM sessions")).scalar()
    assert uid, "a new trip must get a stable id"


def test_skip_duplicates_off_restores_everything(_db):
    data = _backup([_trip(uuid="u1")])
    backup_io.restore_backup(data)
    result = backup_io.restore_backup(data, skip_duplicates=False)
    assert result["restored"] == 1
    assert _counts(_db)["sessions"] == 2


# ---- 5. Each restored trip is atomic ------------------------------------

def test_a_failing_trip_leaves_nothing_behind_and_others_continue(_db, monkeypatch):
    good, bad = _trip(uuid="ok"), _trip(uuid="bad", date="2026-07-05")

    real = db.insert_fish_tx

    def _explode(conn, session_id, rows):
        # Fail only the second trip; the first must survive intact.
        if rows and rows[0].get("species") == "Muskie":
            raise RuntimeError("boom")
        return real(conn, session_id, rows)

    bad["fish"] = [{"species": "Muskie", "length": 40.0}]
    monkeypatch.setattr(db, "insert_fish_tx", _explode)

    result = backup_io.restore_backup(_backup([good, bad]))

    assert result["restored"] == 1
    assert len(result["errors"]) == 1
    counts = _counts(_db)
    assert counts["sessions"] == 1, "the failed trip must not be half-written"
    assert counts["fish"] == 1


def test_filed_date_is_restored_in_the_same_transaction(_db):
    from sqlalchemy import text
    trip = _trip(uuid="u1", dwr_filed=1, dwr_filed_at="2026-07-10")
    backup_io.restore_backup(_backup([trip]))
    with _db.connect() as conn:
        row = conn.execute(
            text("SELECT dwr_filed, dwr_filed_at FROM sessions")).mappings().first()
    assert row["dwr_filed"] == 1
    assert row["dwr_filed_at"] == "2026-07-10"


# ---- 6. CSV formula neutralisation --------------------------------------

@pytest.mark.parametrize("payload", [
    '=cmd|\'/c calc\'!A1',
    '=HYPERLINK("http://evil.example","Click")',
    '+1+1',
    '-2+3',
    '@SUM(A1:A9)',
    '\tsneaky',
])
def test_formula_leading_values_are_defused_in_csv(payload):
    assert backup_io.neutralize_formula(payload) == "'" + payload


@pytest.mark.parametrize("benign", [
    "Caught 3 stripers", "", "Water 82F", "5 - 6 fish", None, 42, 3.5, True,
])
def test_benign_values_are_left_alone(benign):
    assert backup_io.neutralize_formula(benign) == benign


def test_csv_export_defuses_notes_but_json_keeps_the_raw_value(_db):
    attack = '=HYPERLINK("http://evil.example","free lures")'
    data_entry.add_session(
        {"date": "2026-07-04", "location_name": "SML", "num_anglers": 1,
         "notes": attack}, [], [])

    raw_zip = backup_io.build_zip_bytes()
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        sessions_csv = zf.read("sessions.csv").decode()
        payload = json.loads(zf.read(backup_io.JSON_NAME).decode())

    # Parse the CSV rather than substring-matching it: the writer escapes the
    # inner quotes, so the cell's raw text is not the original string.
    cell = pd.read_csv(io.StringIO(sessions_csv))["notes"].iloc[0]
    assert cell == "'" + attack, "CSV must neutralise the formula"
    assert not cell.startswith("="), "a spreadsheet must not see a formula"

    assert payload["sessions"][0]["notes"] == attack, "JSON must keep it raw"


def test_a_defused_backup_round_trips_to_the_original_value(_db):
    attack = "=1+1"
    data_entry.add_session(
        {"date": "2026-07-04", "location_name": "SML", "num_anglers": 1,
         "notes": attack}, [], [])

    payload = backup_io.export_backup()
    from sqlalchemy import text
    with _db.begin() as conn:
        conn.execute(text("DELETE FROM sessions"))

    backup_io.restore_backup(payload)
    with _db.connect() as conn:
        restored = conn.execute(text("SELECT notes FROM sessions")).scalar()
    assert restored == attack, "restore must reproduce exactly what was typed"


def test_csv_helper_handles_an_empty_frame():
    assert backup_io.to_safe_csv(pd.DataFrame(columns=["a", "b"])).startswith("a,b")
