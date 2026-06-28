"""Browse and search past sessions, returning pandas DataFrames for the UI."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import database as db


def list_sessions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> pd.DataFrame:
    """Return a row per session matching the (optional) filters.

    Each row includes ``total_fish`` (sum of catch counts) and a
    comma-joined ``species_list``. ``species`` filters to sessions that
    recorded at least one catch of that species.
    """
    where = []
    params: list = []

    if date_from:
        where.append("s.date >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("s.date <= ?")
        params.append(str(date_to))
    if location:
        where.append("s.location_name LIKE ?")
        params.append(f"%{location}%")
    if species:
        where.append(
            "s.id IN (SELECT session_id FROM fish WHERE species LIKE ?)"
        )
        params.append(f"%{species}%")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # total_fish is the row count; species_list aggregates per-species counts.
    query = f"""
        SELECT
            s.id, s.date, s.start_time, s.end_time, s.hours_fished,
            s.location_name, s.latitude, s.longitude, s.weather,
            s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
            s.num_anglers, s.dwr_filed, s.notes,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish,
            (SELECT MAX(length) FROM fish WHERE session_id = s.id) AS biggest_length,
            COALESCE((
                SELECT GROUP_CONCAT(sp || ' (' || c || ')', ', ')
                FROM (
                    SELECT species AS sp, COUNT(*) AS c
                    FROM fish WHERE session_id = s.id
                    GROUP BY species ORDER BY species
                )
            ), '') AS species_list
        FROM sessions s
        {where_sql}
        ORDER BY s.date DESC, s.start_time DESC
    """
    conn = db.get_connection()
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_session(session_id: int) -> Optional[dict]:
    """Full detail for one session including its individual fish rows."""
    conn = db.get_connection()
    try:
        srow = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if srow is None:
            return None
        fish = conn.execute(
            "SELECT species, length, weight, kept, depth FROM fish WHERE session_id = ? "
            "ORDER BY species, id",
            (session_id,),
        ).fetchall()
        spots = conn.execute(
            "SELECT latitude, longitude, label, caught FROM spots "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        session = dict(srow)
        session["fish"] = [
            {**dict(f), "kept": bool(f["kept"])} for f in fish
        ]
        session["spots"] = [dict(s) for s in spots]
        session["total_fish"] = len(session["fish"])
        return session
    finally:
        conn.close()


def map_rows(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> pd.DataFrame:
    """One row per SESSION (its starting coordinate) for the overview map."""
    where = ["s.latitude IS NOT NULL", "s.longitude IS NOT NULL"]
    params: list = []
    if date_from:
        where.append("s.date >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("s.date <= ?")
        params.append(str(date_to))
    if location:
        where.append("s.location_name LIKE ?")
        params.append(f"%{location}%")
    if species:
        where.append("s.id IN (SELECT session_id FROM fish WHERE species LIKE ?)")
        params.append(f"%{species}%")

    query = f"""
        SELECT
            s.latitude, s.longitude, s.id, s.date, s.start_time, s.end_time,
            s.location_name, s.weather, s.air_temp, s.water_temp,
            s.bait_lure, s.fishing_style,
            (SELECT COUNT(*) FROM fish WHERE session_id = s.id) AS total_fish,
            COALESCE((
                SELECT GROUP_CONCAT(species_name || ' (' || c || ')', ', ')
                FROM (
                    SELECT species AS species_name, COUNT(*) AS c
                    FROM fish WHERE session_id = s.id GROUP BY species ORDER BY species
                )
            ), '') AS species_list
        FROM sessions s
        WHERE {' AND '.join(where)}
        ORDER BY s.date DESC
    """
    conn = db.get_connection()
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def caught_spot_points(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    species: Optional[str] = None,
) -> list:
    """[lat, lon] for every spot where a fish was caught (for the heatmap)."""
    where = ["sp.caught = 1"]
    params: list = []
    if date_from:
        where.append("s.date >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("s.date <= ?")
        params.append(str(date_to))
    if location:
        where.append("s.location_name LIKE ?")
        params.append(f"%{location}%")
    if species:
        where.append("s.id IN (SELECT session_id FROM fish WHERE species LIKE ?)")
        params.append(f"%{species}%")
    query = f"""
        SELECT sp.latitude, sp.longitude
        FROM spots sp JOIN sessions s ON s.id = sp.session_id
        WHERE {' AND '.join(where)}
    """
    conn = db.get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [[r["latitude"], r["longitude"]] for r in rows]
    finally:
        conn.close()


def fish_export() -> pd.DataFrame:
    """Flat one-row-per-fish table (with session context) for CSV export."""
    query = """
        SELECT s.id AS session_id, s.date, s.location_name, s.weather,
               s.air_temp, s.water_temp, s.bait_lure, s.fishing_style,
               f.species, f.length, f.weight
        FROM fish f JOIN sessions s ON s.id = f.session_id
        ORDER BY s.date, f.id
    """
    conn = db.get_connection()
    try:
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def distinct_locations() -> list:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT location_name FROM sessions ORDER BY location_name"
        ).fetchall()
        return [r["location_name"] for r in rows]
    finally:
        conn.close()


def distinct_species() -> list:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT species FROM fish ORDER BY species"
        ).fetchall()
        return [r["species"] for r in rows]
    finally:
        conn.close()


def baits_by_frequency() -> list:
    """Distinct bait/lures, most-used first (for the entry pick-list)."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT bait_lure, COUNT(*) AS n
            FROM sessions
            WHERE bait_lure IS NOT NULL AND TRIM(bait_lure) <> ''
            GROUP BY bait_lure
            ORDER BY n DESC, bait_lure
            """
        ).fetchall()
        return [r["bait_lure"] for r in rows]
    finally:
        conn.close()


def recent_defaults() -> dict:
    """Weather / temps / bait from the most recent session, to pre-fill the form."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT weather, air_temp, water_temp, bait_lure, fishing_style
            FROM sessions
            ORDER BY date DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
