"""Browse and search past sessions, returning pandas DataFrames for the UI.

All queries are scoped to db.get_current_user() so each angler sees only
their own data.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import text

from . import database as db


def _user() -> str:
    return db.get_current_user()


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
        where.append("s.location_name ILIKE :location")
        params["location"] = f"%{location}%"
    if species:
        where.append("s.id IN (SELECT session_id FROM fish WHERE species ILIKE :species)")
        params["species"] = f"%{species}%"

    where_sql = "WHERE " + " AND ".join(where)

    query = text(f"""
        SELECT
            s.id, s.date, s.start_time, s.end_time, s.hours_fished,
            s.location_name, s.latitude, s.longitude, s.weather,
            s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
            s.num_anglers, s.dwr_filed, s.notes,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish,
            (SELECT MAX(length) FROM fish WHERE session_id = s.id) AS biggest_length,
            COALESCE((
                SELECT STRING_AGG(sp || ' (' || c::text || ')', ', ' ORDER BY sp)
                FROM (
                    SELECT species AS sp, COUNT(*) AS c
                    FROM fish WHERE session_id = s.id
                    GROUP BY species
                ) sub
            ), '') AS species_list
        FROM sessions s
        {where_sql}
        ORDER BY s.date DESC, s.start_time DESC
    """)

    with db.get_engine().connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


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
                "SELECT latitude, longitude, label, caught FROM spots "
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
        where.append("s.location_name ILIKE :location")
        params["location"] = f"%{location}%"
    if species:
        where.append("s.id IN (SELECT session_id FROM fish WHERE species ILIKE :species)")
        params["species"] = f"%{species}%"

    query = text(f"""
        SELECT
            s.latitude, s.longitude, s.id, s.date, s.start_time, s.end_time,
            s.location_name, s.weather, s.air_temp, s.water_temp,
            s.bait_lure, s.fishing_style,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish,
            COALESCE((
                SELECT STRING_AGG(sp || ' (' || c::text || ')', ', ' ORDER BY sp)
                FROM (
                    SELECT species AS sp, COUNT(*) AS c
                    FROM fish WHERE session_id = s.id GROUP BY species
                ) sub
            ), '') AS species_list
        FROM sessions s
        WHERE {' AND '.join(where)}
        ORDER BY s.date DESC
    """)

    with db.get_engine().connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


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
        where.append("s.location_name ILIKE :location")
        params["location"] = f"%{location}%"
    if species:
        where.append("s.id IN (SELECT session_id FROM fish WHERE species ILIKE :species)")
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
    """Return {day_of_month: {total_fish, location, moon_phase}} for the calendar view.

    Multiple sessions on the same day are merged: fish counts sum, first location shown.
    """
    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]
    date_from = f"{year}-{month:02d}-01"
    date_to   = f"{year}-{month:02d}-{last_day:02d}"
    query = text("""
        SELECT
            EXTRACT(DAY FROM s.date::date)::int AS day,
            COUNT(f.id)                          AS total_fish,
            MIN(s.location_name)                 AS location_name,
            MIN(s.moon_phase)                    AS moon_phase
        FROM sessions s
        LEFT JOIN fish f ON f.session_id = s.id
        WHERE s.user_email = :email
          AND s.date >= :date_from
          AND s.date <= :date_to
        GROUP BY EXTRACT(DAY FROM s.date::date)::int
        ORDER BY day
    """)
    with db.get_engine().connect() as conn:
        rows = conn.execute(query, {
            "email": _user(), "date_from": date_from, "date_to": date_to,
        }).mappings().all()
    return {
        int(r["day"]): {
            "total_fish": int(r["total_fish"]),
            "location":   (r["location_name"] or "")[:22],
            "moon_phase": r["moon_phase"] or "",
        }
        for r in rows
    }


def fish_export() -> pd.DataFrame:
    """Flat one-row-per-fish table for CSV export."""
    query = text("""
        SELECT s.id AS session_id, s.date, s.location_name, s.weather,
               s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
               f.species, f.length, f.weight, f.depth
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
