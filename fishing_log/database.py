"""Cloud database layer: SQLAlchemy + psycopg2 connecting to Supabase Postgres.

All user data is isolated by user_email. Call set_current_user(email) once at
the top of each Streamlit script run (in main()) before any DB operations.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Stubs for legacy modules that reference these paths (not used in cloud version)
DATA_DIR = Path("/tmp/fishing_log_data")
PROJECT_ROOT = Path("/tmp")

# ---------------------------------------------------------------------------
# Per-session user context (thread-local so each Streamlit session is isolated)
# ---------------------------------------------------------------------------

_local = threading.local()


def set_current_user(email: str) -> None:
    """Call once per script run with the logged-in user's email."""
    _local.user_email = email.lower().strip()


def get_current_user() -> str:
    return getattr(_local, "user_email", "")


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
    """Return the SQLAlchemy engine (used by pandas read_sql_query)."""
    return get_engine()


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

def insert_session(session: dict) -> int:
    """Insert one session and return its new id."""
    user_email = get_current_user()
    fields = ("user_email",) + SESSION_FIELDS
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{f}" for f in fields)
    params: dict = {"user_email": user_email}
    params.update({f: session.get(f) for f in SESSION_FIELDS})
    with get_engine().begin() as conn:
        result = conn.execute(
            text(f"INSERT INTO sessions ({cols}) VALUES ({placeholders}) RETURNING id"),
            params,
        )
        return int(result.scalar())


def insert_fish(session_id: int, fish_rows) -> None:
    """Insert one row per fish. Each item: {species, length, weight, kept?, depth?}."""
    rows = [
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
    if not rows:
        return
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fish (session_id, species, length, weight, kept, depth) "
                "VALUES (:session_id, :species, :length, :weight, :kept, :depth)"
            ),
            rows,
        )


def insert_spots(session_id: int, spots) -> None:
    """Insert spot rows. Each item: {lat, lon, label?, caught?}."""
    rows = [
        {
            "session_id": session_id,
            "latitude": float(s["lat"]),
            "longitude": float(s["lon"]),
            "label": s.get("label"),
            "caught": int(bool(s.get("caught"))),
        }
        for s in spots
        if s.get("lat") is not None and s.get("lon") is not None
    ]
    if not rows:
        return
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO spots (session_id, latitude, longitude, label, caught) "
                "VALUES (:session_id, :latitude, :longitude, :label, :caught)"
            ),
            rows,
        )


def insert_photo(session_id: int, path: str, caption: Optional[str] = None) -> int:
    """Record a photo path. Not yet supported in cloud version."""
    raise NotImplementedError("Photo storage not yet available in the cloud version.")


def session_count() -> int:
    user_email = get_current_user()
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_email = :email"),
            {"email": user_email},
        )
        return int(result.scalar())


def delete_all_sessions() -> int:
    """Delete all sessions for the current user. Returns rows removed."""
    user_email = get_current_user()
    with get_engine().begin() as conn:
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
