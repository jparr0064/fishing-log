"""Cloud database layer: SQLAlchemy + psycopg2 connecting to Supabase Postgres.

All user data is isolated by user_email. Call set_current_user(email) once at
the top of each Streamlit script run (in main()) before any DB operations.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Stubs for legacy modules that reference these paths (not used in cloud version)
DATA_DIR = Path("/tmp/fishing_log_data")
PROJECT_ROOT = Path("/tmp")

# ---------------------------------------------------------------------------
# Per-session user context — stored in st.session_state so widget callbacks
# that run on a different thread still see the correct user.
# ---------------------------------------------------------------------------


def set_current_user(email: str) -> None:
    """Call once per script run with the logged-in user's email."""
    st.session_state["user_email"] = email.lower().strip()


def get_current_user() -> str:
    return st.session_state.get("user_email", "")


# ---------------------------------------------------------------------------
# Engine (created once per server process)
# ---------------------------------------------------------------------------

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError(
                "DATABASE_URL not configured. "
                "Add it to .streamlit/secrets.toml as database_url = '...'"
            )
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return _engine


def get_connection():
    """Return the SQLAlchemy engine (used by pandas read_sql_query).

    Deprecated for query use: it hands back a bare engine, so anything running
    on it gets a connection with no RLS scope applied and will see nothing once
    the app connects as ``fishing_app``. Use :func:`read_connection` or
    :func:`write_transaction` instead.
    """
    return get_engine()


# ---------------------------------------------------------------------------
# RLS scoping (CR-2)
#
# Postgres policies on sessions/fish/spots filter on a per-transaction setting,
# app.user_email. Every connection must publish the verified identity before it
# queries, or the policies match nothing and the user sees an empty app.
#
# The application's own `WHERE user_email = :email` predicates stay exactly
# where they are. They are no longer the only thing standing between two club
# members' data, but they remain the first line — defence in depth, per CR-2.
# ---------------------------------------------------------------------------


def _apply_user_scope(conn) -> None:
    """Publish the current user to this transaction for RLS policies.

    Uses ``set_config(..., is_local => true)`` rather than ``SET LOCAL``: SET
    does not accept bind parameters, so the literal form would mean splicing an
    email into SQL. Both are transaction-scoped, which is what makes this safe
    under connection pooling — the value is discarded at COMMIT or ROLLBACK and
    cannot leak into the next checkout of the same connection.

    No-op on SQLite: the test suite runs in-memory and has no RLS. Tests still
    cover isolation through the application predicates (test_write_scoping);
    the database-level guarantee is exercised by the SQL in
    migrations/001_rls_least_privilege.sql.
    """
    if conn.dialect.name != "postgresql":
        return
    conn.execute(
        text("SELECT set_config('app.user_email', :email, true)"),
        {"email": get_current_user()},
    )


@contextmanager
def read_connection():
    """A connection for reads, scoped to the current user.

    The set_config call opens the implicit transaction, so every later query on
    this connection sees the setting. Nothing is committed — the connection is
    rolled back on exit.
    """
    with get_engine().connect() as conn:
        _apply_user_scope(conn)
        yield conn


@contextmanager
def write_transaction():
    """A transaction for writes, scoped to the current user.

    Commits on success, rolls back on any exception — so an aggregate write
    that fails part-way leaves nothing behind (see CR-4).
    """
    with get_engine().begin() as conn:
        _apply_user_scope(conn)
        yield conn


# ---------------------------------------------------------------------------
# Session fields (columns written on insert/update)
# ---------------------------------------------------------------------------

SESSION_FIELDS = (
    "date", "start_time", "end_time", "hours_fished",
    "location_name", "latitude", "longitude",
    "weather", "air_temp", "water_temp",
    "bait_lure", "fishing_style", "num_anglers", "dwr_filed",
    "notes", "moon_phase",
)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

# The *_tx functions take an existing connection so a caller can compose a
# whole trip — session + fish + spots — inside ONE transaction (CR-4). The
# public wrappers below keep the original single-statement API for callers that
# genuinely only write one thing.


# Whether sessions.trip_uuid exists (migrations/003_trip_uuid.sql). Cached per
# engine so the app works either side of that migration without paying for an
# inspector round trip on every write. Keyed by engine identity so the test
# suite, which swaps in a fresh engine per test, is not poisoned by the cache.
_trip_uuid_support: dict = {}


def has_trip_uuid_column() -> bool:
    """True when sessions.trip_uuid is present."""
    engine = get_engine()
    key = id(engine)
    if key not in _trip_uuid_support:
        try:
            from sqlalchemy import inspect as sa_inspect
            columns = {c["name"] for c in sa_inspect(engine).get_columns("sessions")}
            _trip_uuid_support[key] = "trip_uuid" in columns
        except Exception:
            _trip_uuid_support[key] = False
    return _trip_uuid_support[key]


def insert_session_tx(conn, session: dict, trip_uuid: Optional[str] = None) -> int:
    """Insert one session on an existing transaction; return its new id.

    ``trip_uuid`` is the stable identifier used to make restore idempotent. A
    new trip gets a fresh one; a restored trip reuses the id from the backup so
    restoring twice does not duplicate it. Skipped entirely when the column is
    absent, so this works before migration 003 has been applied.
    """
    fields = ("user_email",) + SESSION_FIELDS
    params: dict = {"user_email": get_current_user()}
    params.update({f: session.get(f) for f in SESSION_FIELDS})

    if has_trip_uuid_column():
        fields = fields + ("trip_uuid",)
        params["trip_uuid"] = trip_uuid or str(uuid.uuid4())

    cols = ", ".join(fields)
    placeholders = ", ".join(f":{f}" for f in fields)
    result = conn.execute(
        text(f"INSERT INTO sessions ({cols}) VALUES ({placeholders}) RETURNING id"),
        params,
    )
    return int(result.scalar())


def insert_session(session: dict) -> int:
    """Insert one session in its own transaction and return its new id."""
    with write_transaction() as conn:
        return insert_session_tx(conn, session)


def _assert_session_owned(conn, session_id: int) -> None:
    """Raise if session_id doesn't belong to the current user."""
    result = conn.execute(
        text("SELECT 1 FROM sessions WHERE id = :id AND user_email = :email"),
        {"id": session_id, "email": get_current_user()},
    )
    if result.fetchone() is None:
        raise PermissionError(f"Session {session_id} not found or not owned by current user.")


def _fish_rows(session_id: int, fish_rows) -> list:
    return [
        {
            "session_id": session_id,
            "species": f["species"],
            "length": float(f.get("length") or 0),
            "weight": float(f.get("weight") or 0),
            "kept": int(bool(f.get("kept"))),
            "depth": float(f["depth"]) if f.get("depth") else None,
        }
        for f in fish_rows
        if f.get("species")
    ]


def insert_fish_tx(conn, session_id: int, fish_rows) -> None:
    """Insert one row per fish on an existing transaction."""
    rows = _fish_rows(session_id, fish_rows)
    if not rows:
        return
    _assert_session_owned(conn, session_id)
    conn.execute(
        text(
            "INSERT INTO fish (session_id, species, length, weight, kept, depth) "
            "VALUES (:session_id, :species, :length, :weight, :kept, :depth)"
        ),
        rows,
    )


def insert_fish(session_id: int, fish_rows) -> None:
    """Insert one row per fish. Each item: {species, length, weight, kept?, depth?}."""
    if not _fish_rows(session_id, fish_rows):
        return
    with write_transaction() as conn:
        insert_fish_tx(conn, session_id, fish_rows)


def insert_spots(session_id: int, spots) -> None:
    """Insert spot rows. Each item: {lat, lon, label?, caught?, fish_count?}.

    ``fish_count`` is how many fish were caught at the spot (nullable —
    legacy rows recorded only the boolean ``caught`` flag).
    """
    if not _spot_rows(session_id, spots):
        return
    with write_transaction() as conn:
        insert_spots_tx(conn, session_id, spots)


def _spot_rows(session_id: int, spots) -> list:
    return [
        {
            "session_id": session_id,
            "latitude": float(s["lat"]),
            "longitude": float(s["lon"]),
            "label": s.get("label"),
            "caught": int(bool(s.get("caught")) or (s.get("fish_count") or 0) > 0),
            "fish_count": int(s["fish_count"]) if s.get("fish_count") is not None else None,
        }
        for s in spots
        if s.get("lat") is not None and s.get("lon") is not None
    ]


def insert_spots_tx(conn, session_id: int, spots) -> None:
    """Insert spot rows on an existing transaction."""
    rows = _spot_rows(session_id, spots)
    if not rows:
        return
    _assert_session_owned(conn, session_id)
    conn.execute(
        text(
            "INSERT INTO spots (session_id, latitude, longitude, label, caught, fish_count) "
            "VALUES (:session_id, :latitude, :longitude, :label, :caught, :fish_count)"
        ),
        rows,
    )


def insert_photo(session_id: int, path: str, caption: Optional[str] = None) -> int:
    """Record a photo path. Not yet supported in cloud version."""
    raise NotImplementedError("Photo storage not yet available in the cloud version.")


def session_count() -> int:
    user_email = get_current_user()
    with read_connection() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_email = :email"),
            {"email": user_email},
        )
        return int(result.scalar())


def delete_all_sessions() -> int:
    """Delete all sessions for the current user. Returns rows removed."""
    user_email = get_current_user()
    with write_transaction() as conn:
        result = conn.execute(
            text("DELETE FROM sessions WHERE user_email = :email"),
            {"email": user_email},
        )
        return result.rowcount


# Legacy stubs kept so import-time references don't break during transition
def init_db(*args, **kwargs) -> None:
    pass  # Tables already created in Supabase


def set_db_path(*args, **kwargs) -> None:
    pass


def get_db_path() -> str:
    return "supabase"
