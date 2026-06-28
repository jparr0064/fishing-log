"""Database layer: connection management, schema creation, and low-level CRUD.

The on-disk SQLite file lives in ``<project>/data/fishing_log.db`` by default.
Everything here is plain ``sqlite3`` (standard library) so the app runs fully
offline with no external database service.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

# Project root = parent of the ``fishing_log`` package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "fishing_log.db"
PHOTOS_DIR = DATA_DIR / "photos"

# Allow tests / callers to override the database location.
_db_path: Path = DEFAULT_DB_PATH


def set_db_path(path: str | Path) -> None:
    """Point the module at a different database file (used by tests)."""
    global _db_path
    _db_path = Path(path)


def get_db_path() -> Path:
    return _db_path


def get_connection() -> sqlite3.Connection:
    """Return a connection with row access by name and foreign keys enabled."""
    path = get_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,            -- ISO YYYY-MM-DD
    start_time    TEXT,                        -- HH:MM
    end_time      TEXT,                        -- HH:MM
    hours_fished  REAL,
    location_name TEXT    NOT NULL,
    latitude      REAL,
    longitude     REAL,
    weather       TEXT,
    air_temp      REAL,
    water_temp    REAL,
    bait_lure     TEXT,
    fishing_style TEXT,
    num_anglers   INTEGER NOT NULL DEFAULT 1,
    dwr_filed     INTEGER NOT NULL DEFAULT 0,   -- 1 = striper report filed to DWR
    notes         TEXT,
    moon_phase    TEXT                          -- auto-computed from session date
);

CREATE TABLE IF NOT EXISTS catches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    species    TEXT    NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    path       TEXT    NOT NULL,            -- relative to project root
    caption    TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- One row per individual fish (replaces the aggregate `catches` table; that
-- table is kept as a backup and is no longer written to).
CREATE TABLE IF NOT EXISTS fish (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    species    TEXT    NOT NULL,
    length     REAL    NOT NULL DEFAULT 0,
    weight     REAL    NOT NULL DEFAULT 0,
    kept       INTEGER NOT NULL DEFAULT 0,   -- 1 = harvested/kept, 0 = released
    depth      REAL,                         -- depth (ft) where fish was caught
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- One or more map spots per session (a trolling run can cover several pins).
CREATE TABLE IF NOT EXISTS spots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    latitude   REAL    NOT NULL,
    longitude  REAL    NOT NULL,
    label      TEXT,
    caught     INTEGER NOT NULL DEFAULT 0,   -- 1 if a fish was caught at this spot
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_catches_session ON catches(session_id);
CREATE INDEX IF NOT EXISTS idx_catches_species ON catches(species);
CREATE INDEX IF NOT EXISTS idx_photos_session ON photos(session_id);
CREATE INDEX IF NOT EXISTS idx_fish_session ON fish(session_id);
CREATE INDEX IF NOT EXISTS idx_fish_species ON fish(species);
CREATE INDEX IF NOT EXISTS idx_spots_session ON spots(session_id);
"""


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    """Create tables/indexes if missing and apply additive migrations.

    Migrations only ADD columns — they never drop tables or data, so existing
    sessions and photos are preserved.
    """
    own = conn is None
    conn = conn or get_connection()
    try:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def _add_columns(conn: sqlite3.Connection, table: str, additions: dict) -> None:
    """Add missing columns to a table if the table exists (additive, safe)."""
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not has_table:
        return
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, ddl in additions.items():
        if col not in existing:
            conn.execute(ddl)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Apply additive migrations: new columns and one-time data backfills."""
    _add_columns(conn, "sessions", {
        "fishing_style": "ALTER TABLE sessions ADD COLUMN fishing_style TEXT",
        "num_anglers": "ALTER TABLE sessions ADD COLUMN num_anglers INTEGER NOT NULL DEFAULT 1",
        "dwr_filed": "ALTER TABLE sessions ADD COLUMN dwr_filed INTEGER NOT NULL DEFAULT 0",
        "moon_phase": "ALTER TABLE sessions ADD COLUMN moon_phase TEXT",
    })
    _add_columns(conn, "spots", {
        "caught": "ALTER TABLE spots ADD COLUMN caught INTEGER NOT NULL DEFAULT 0",
    })
    _add_columns(conn, "fish", {
        "kept": "ALTER TABLE fish ADD COLUMN kept INTEGER NOT NULL DEFAULT 0",
        "depth": "ALTER TABLE fish ADD COLUMN depth REAL",
    })

    # Version-guarded one-time migrations (run once each, never duplicate):
    #   v1: expand aggregate `catches` into individual `fish` rows.
    #   v2: seed `spots` from each session's single lat/long.
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        _backfill_fish_from_catches(conn)
    if version < 2:
        _backfill_spots_from_sessions(conn)
    if version < 2:
        conn.execute("PRAGMA user_version = 2")


def _backfill_fish_from_catches(conn: sqlite3.Connection) -> None:
    """Copy legacy aggregate catches into the per-fish table (idempotent caller)."""
    has_catches = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='catches'"
    ).fetchone()
    if not has_catches:
        return
    for row in conn.execute("SELECT session_id, species, count FROM catches").fetchall():
        for _ in range(int(row["count"] or 0)):
            conn.execute(
                "INSERT INTO fish (session_id, species, length, weight) VALUES (?, ?, 0, 0)",
                (row["session_id"], row["species"]),
            )


def _backfill_spots_from_sessions(conn: sqlite3.Connection) -> None:
    """Seed the spots table with each session's existing single coordinate."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    if not {"latitude", "longitude"} <= cols:
        return
    has_spots = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spots'"
    ).fetchone()
    if not has_spots:
        return
    rows = conn.execute(
        "SELECT id, latitude, longitude FROM sessions "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO spots (session_id, latitude, longitude) VALUES (?, ?, ?)",
            (r["id"], r["latitude"], r["longitude"]),
        )


def insert_spots(conn: sqlite3.Connection, session_id: int, spots) -> None:
    """Insert spot rows. Each item: {lat, lon, label?, caught?}. Does not commit."""
    rows = [
        (session_id, float(s["lat"]), float(s["lon"]), s.get("label"),
         int(bool(s.get("caught"))))
        for s in spots
        if s.get("lat") is not None and s.get("lon") is not None
    ]
    if rows:
        conn.executemany(
            "INSERT INTO spots (session_id, latitude, longitude, label, caught) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def insert_fish(conn: sqlite3.Connection, session_id: int, fish_rows) -> None:
    """Insert one row per fish. Each item: {species, length, weight, kept?, depth?}. No commit."""
    rows = [
        (
            session_id,
            f["species"],
            float(f.get("length") or 0),
            float(f.get("weight") or 0),
            int(bool(f.get("kept"))),
            float(f["depth"]) if f.get("depth") else None,
        )
        for f in fish_rows
        if f.get("species")
    ]
    if rows:
        conn.executemany(
            "INSERT INTO fish (session_id, species, length, weight, kept, depth) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


def session_count(conn: Optional[sqlite3.Connection] = None) -> int:
    own = conn is None
    conn = conn or get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
        return int(row["n"])
    finally:
        if own:
            conn.close()


# --- Low-level inserts -----------------------------------------------------

SESSION_FIELDS = (
    "date",
    "start_time",
    "end_time",
    "hours_fished",
    "location_name",
    "latitude",
    "longitude",
    "weather",
    "air_temp",
    "water_temp",
    "bait_lure",
    "fishing_style",
    "num_anglers",
    "dwr_filed",
    "notes",
    "moon_phase",
)


def insert_session(conn: sqlite3.Connection, session: dict) -> int:
    """Insert one session row and return its new id. Does not commit."""
    cols = ", ".join(SESSION_FIELDS)
    placeholders = ", ".join(f":{f}" for f in SESSION_FIELDS)
    params = {f: session.get(f) for f in SESSION_FIELDS}
    cur = conn.execute(
        f"INSERT INTO sessions ({cols}) VALUES ({placeholders})", params
    )
    return int(cur.lastrowid)


def insert_catches(
    conn: sqlite3.Connection, session_id: int, catches: Iterable[dict]
) -> None:
    """Insert catch rows for a session. Does not commit."""
    rows = [
        (session_id, c["species"], int(c.get("count", 0)))
        for c in catches
        if c.get("species")
    ]
    if rows:
        conn.executemany(
            "INSERT INTO catches (session_id, species, count) VALUES (?, ?, ?)",
            rows,
        )


def insert_photo(
    conn: sqlite3.Connection, session_id: int, path: str, caption: Optional[str] = None
) -> int:
    """Record one photo (path relative to project root). Does not commit."""
    cur = conn.execute(
        "INSERT INTO photos (session_id, path, caption) VALUES (?, ?, ?)",
        (session_id, path, caption),
    )
    return int(cur.lastrowid)


def delete_all_sessions(conn: Optional[sqlite3.Connection] = None) -> int:
    """Delete every session (catches and photo rows cascade). Returns rows removed."""
    own = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.execute("DELETE FROM sessions")
        conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()
