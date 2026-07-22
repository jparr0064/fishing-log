"""Browse and search past sessions, returning pandas DataFrames for the UI.

All queries are scoped to db.get_current_user() so each angler sees only
their own data.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import bindparam, text

from . import database as db


def _user() -> str:
    return db.get_current_user()


def _like(col: str, param: str) -> str:
    """Case-insensitive LIKE that works on both Postgres and SQLite."""
    return f"LOWER({col}) LIKE LOWER(:{param})"


def _species_list_map(engine, session_ids: list) -> dict:
    """Return {session_id: 'Bass (3), Striper (1)'} for the given session IDs."""
    if not session_ids:
        return {}
    q = text(
        "SELECT session_id, species, COUNT(*) AS cnt "
        "FROM fish WHERE session_id IN :sids "
        "GROUP BY session_id, species ORDER BY species"
    ).bindparams(bindparam("sids", expanding=True))
    with engine.connect() as conn:
        rows = conn.execute(q, {"sids": session_ids}).mappings().all()
    result: dict = {}
    for r in rows:
        sid = int(r["session_id"])
        entry = f"{r['species']} ({int(r['cnt'])})"
        result[sid] = f"{result[sid]}, {entry}" if sid in result else entry
    return result


def list_sessions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> pd.DataFrame:
    where = ["s.user_email = :user_email"]
    params: dict = {"user_email": _user()}

    if date_from:
        where.append("s.date >= :date_from")
        params["date_from"] = str(date_from)
    if date_to:
        where.append("s.date <= :date_to")
        params["date_to"] = str(date_to)
    if location:
        where.append(_like("s.location_name", "location"))
        params["location"] = f"%{location}%"
    if species:
        where.append(f"s.id IN (SELECT session_id FROM fish WHERE {_like('species', 'species')})")
        params["species"] = f"%{species}%"

    where_sql = "WHERE " + " AND ".join(where)

    query = text(f"""
        SELECT
            s.id, s.date, s.start_time, s.end_time, s.hours_fished,
            s.location_name, s.latitude, s.longitude, s.weather,
            s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
            s.num_anglers, s.dwr_filed, s.notes,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish,
            (SELECT MAX(length) FROM fish WHERE session_id = s.id) AS biggest_length
        FROM sessions s
        {where_sql}
        ORDER BY s.date DESC, (s.start_time IS NULL), s.start_time DESC
    """)

    engine = db.get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    sl_map = _species_list_map(engine, df["id"].tolist() if not df.empty else [])
    df["species_list"] = df["id"].map(sl_map).fillna("") if not df.empty else ""
    return df


def get_session(session_id: int) -> Optional[dict]:
    """Full detail for one session (scoped to current user)."""
    engine = db.get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM sessions WHERE id = :id AND user_email = :email"),
            {"id": session_id, "email": _user()},
        ).mappings().first()
        if row is None:
            return None

        fish = conn.execute(
            text(
                "SELECT species, length, weight, kept, depth FROM fish "
                "WHERE session_id = :sid ORDER BY species, id"
            ),
            {"sid": session_id},
        ).mappings().all()

        spots = conn.execute(
            text(
                "SELECT latitude, longitude, label, caught, fish_count FROM spots "
                "WHERE session_id = :sid ORDER BY id"
            ),
            {"sid": session_id},
        ).mappings().all()

    session = dict(row)
    session["fish"] = [{**dict(f), "kept": bool(f["kept"])} for f in fish]
    session["spots"] = [dict(s) for s in spots]
    session["total_fish"] = len(session["fish"])
    return session


def map_rows(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> pd.DataFrame:
    """One row per session (starting coordinate) for the overview map."""
    where = ["s.user_email = :user_email", "s.latitude IS NOT NULL", "s.longitude IS NOT NULL"]
    params: dict = {"user_email": _user()}

    if date_from:
        where.append("s.date >= :date_from")
        params["date_from"] = str(date_from)
    if date_to:
        where.append("s.date <= :date_to")
        params["date_to"] = str(date_to)
    if location:
        where.append(_like("s.location_name", "location"))
        params["location"] = f"%{location}%"
    if species:
        where.append(f"s.id IN (SELECT session_id FROM fish WHERE {_like('species', 'species')})")
        params["species"] = f"%{species}%"

    query = text(f"""
        SELECT
            s.latitude, s.longitude, s.id, s.date, s.start_time, s.end_time,
            s.location_name, s.weather, s.air_temp, s.water_temp,
            s.bait_lure, s.fishing_style,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish
        FROM sessions s
        WHERE {' AND '.join(where)}
        ORDER BY s.date DESC
    """)

    engine = db.get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    sl_map = _species_list_map(engine, df["id"].tolist() if not df.empty else [])
    df["species_list"] = df["id"].map(sl_map).fillna("") if not df.empty else ""
    return df


def caught_spot_points(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> list:
    """[lat, lon] for every spot where a fish was caught (for the heatmap)."""
    where = ["sp.caught = 1", "s.user_email = :user_email"]
    params: dict = {"user_email": _user()}

    if date_from:
        where.append("s.date >= :date_from")
        params["date_from"] = str(date_from)
    if date_to:
        where.append("s.date <= :date_to")
        params["date_to"] = str(date_to)
    if location:
        where.append(_like("s.location_name", "location"))
        params["location"] = f"%{location}%"
    if species:
        where.append(f"s.id IN (SELECT session_id FROM fish WHERE {_like('species', 'species')})")
        params["species"] = f"%{species}%"

    query = text(f"""
        SELECT sp.latitude, sp.longitude
        FROM spots sp JOIN sessions s ON s.id = sp.session_id
        WHERE {' AND '.join(where)}
    """)

    with db.get_engine().connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [[r["latitude"], r["longitude"]] for r in rows]


def calendar_month(year: int, month: int) -> dict:
    """Return {day_of_month: [{session_id, total_fish, location, moon_phase}, ...]} for the calendar."""
    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]
    date_from = f"{year}-{month:02d}-01"
    date_to   = f"{year}-{month:02d}-{last_day:02d}"
    query = text("""
        SELECT
            s.id                AS session_id,
            s.date,
            COUNT(f.id)         AS total_fish,
            s.location_name,
            s.moon_phase,
            s.start_time
        FROM sessions s
        LEFT JOIN fish f ON f.session_id = s.id
        WHERE s.user_email = :email
          AND s.date >= :date_from
          AND s.date <= :date_to
        GROUP BY s.id, s.date, s.location_name, s.moon_phase, s.start_time
        ORDER BY s.date, s.start_time
    """)
    with db.get_engine().connect() as conn:
        rows = conn.execute(query, {
            "email": _user(), "date_from": date_from, "date_to": date_to,
        }).mappings().all()
    result: dict = {}
    for r in rows:
        date_str = str(r["date"])[:10]
        day = int(date_str.split("-")[2])
        result.setdefault(day, []).append({
            "session_id": int(r["session_id"]),
            "total_fish": int(r["total_fish"]),
            "location":   (r["location_name"] or "")[:22],
            "moon_phase": r["moon_phase"] or "",
        })
    return result


def fish_export() -> pd.DataFrame:
    """Flat one-row-per-fish table for CSV export (stable IDs + kept/released)."""
    query = text("""
        SELECT f.id AS fish_id, s.id AS session_id, s.date, s.location_name,
               s.weather, s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
               f.species, f.length, f.weight, f.depth, f.kept
        FROM fish f JOIN sessions s ON s.id = f.session_id
        WHERE s.user_email = :email
        ORDER BY s.date, f.id
    """)
    with db.get_engine().connect() as conn:
        return pd.read_sql_query(query, conn, params={"email": _user()})


def distinct_locations() -> list:
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT location_name FROM sessions "
                 "WHERE user_email = :email ORDER BY location_name"),
            {"email": _user()},
        ).mappings().all()
    return [r["location_name"] for r in rows]


def distinct_species() -> list:
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT f.species FROM fish f "
                 "JOIN sessions s ON s.id = f.session_id "
                 "WHERE s.user_email = :email ORDER BY f.species"),
            {"email": _user()},
        ).mappings().all()
    return [r["species"] for r in rows]


def baits_by_frequency() -> list:
    """Distinct bait/lures, most-used first."""
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT bait_lure, COUNT(*) AS n
                FROM sessions
                WHERE user_email = :email
                  AND bait_lure IS NOT NULL AND TRIM(bait_lure) <> ''
                GROUP BY bait_lure
                ORDER BY n DESC, bait_lure
            """),
            {"email": _user()},
        ).mappings().all()
    return [r["bait_lure"] for r in rows]


def recent_defaults() -> dict:
    """Weather / temps / bait from the most recent session, to pre-fill the form."""
    with db.get_engine().connect() as conn:
        row = conn.execute(
            text("""
                SELECT weather, air_temp, water_temp, bait_lure, fishing_style
                FROM sessions
                WHERE user_email = :email
                ORDER BY date DESC, id DESC
                LIMIT 1
            """),
            {"email": _user()},
        ).mappings().first()
    return dict(row) if row else {}


def last_spot():
    """(lat, lon) of the most recent session with coordinates, or None.

    Used to center the spot-picker map on the user's last fishing spot —
    most anglers return to the same water.
    """
    with db.get_engine().connect() as conn:
        row = conn.execute(
            text("""
                SELECT latitude, longitude
                FROM sessions
                WHERE user_email = :email
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY date DESC, id DESC
                LIMIT 1
            """),
            {"email": _user()},
        ).mappings().first()
    return (float(row["latitude"]), float(row["longitude"])) if row else None
