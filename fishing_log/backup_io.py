"""Full backup and restore for one angler's data.

Backup = a single ZIP containing:
  * sessions.csv — one row per trip (every column)
  * fish.csv     — one row per fish, with stable IDs and kept/released
  * spots.csv    — route order, coordinates, caught flag, per-spot fish count
  * backup.json  — the complete restorable record (sessions with nested
                   fish + spots), version-stamped

Restore = feed backup.json (or the whole ZIP) back in; every trip is
re-validated through data_entry.add_session, so a restore can never write
rows the app itself would reject. All reads/writes are scoped to
db.get_current_user() like everything else.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date as _date
from typing import Optional

import pandas as pd
from sqlalchemy import text

from . import database as db

BACKUP_VERSION = 1
JSON_NAME = "backup.json"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _sessions_df() -> pd.DataFrame:
    q = text("""
        SELECT id AS session_id, date, start_time, end_time, hours_fished,
               location_name, latitude, longitude, weather, air_temp,
               water_temp, bait_lure, fishing_style, num_anglers,
               dwr_filed, dwr_filed_at, notes, moon_phase
        FROM sessions WHERE user_email = :email
        ORDER BY date, id
    """)
    with db.get_engine().connect() as conn:
        return pd.read_sql_query(q, conn, params={"email": db.get_current_user()})


def _fish_df() -> pd.DataFrame:
    q = text("""
        SELECT f.id AS fish_id, f.session_id, s.date, s.location_name,
               f.species, f.length, f.weight, f.kept, f.depth
        FROM fish f JOIN sessions s ON s.id = f.session_id
        WHERE s.user_email = :email
        ORDER BY f.session_id, f.id
    """)
    with db.get_engine().connect() as conn:
        return pd.read_sql_query(q, conn, params={"email": db.get_current_user()})


def _spots_df() -> pd.DataFrame:
    q = text("""
        SELECT sp.id AS spot_id, sp.session_id, s.date,
               sp.latitude, sp.longitude, sp.label, sp.caught, sp.fish_count
        FROM spots sp JOIN sessions s ON s.id = sp.session_id
        WHERE s.user_email = :email
        ORDER BY sp.session_id, sp.id
    """)
    with db.get_engine().connect() as conn:
        df = pd.read_sql_query(q, conn, params={"email": db.get_current_user()})
    if not df.empty:
        # Route order within each trip (spots were inserted in click order).
        df["route_order"] = df.groupby("session_id").cumcount() + 1
    else:
        df["route_order"] = pd.Series(dtype=int)
    return df


def _s(v):
    """String-ish column value → Python str or None (pandas NaN-safe)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v


def export_backup() -> dict:
    """The complete restorable record for the current user."""
    sessions = _sessions_df()
    fish = _fish_df()
    spots = _spots_df()

    by_sid_fish: dict = {}
    for r in fish.itertuples():
        by_sid_fish.setdefault(int(r.session_id), []).append({
            "species": r.species,
            "length": None if pd.isna(r.length) else float(r.length),
            "weight": None if pd.isna(r.weight) else float(r.weight),
            "kept": bool(r.kept),
            "depth": None if pd.isna(r.depth) else float(r.depth),
        })
    by_sid_spots: dict = {}
    for r in spots.itertuples():
        by_sid_spots.setdefault(int(r.session_id), []).append({
            "lat": None if pd.isna(r.latitude) else float(r.latitude),
            "lon": None if pd.isna(r.longitude) else float(r.longitude),
            "label": None if (r.label is None or (isinstance(r.label, float) and pd.isna(r.label))) else r.label,
            "caught": bool(r.caught),
            "fish_count": None if pd.isna(r.fish_count) else int(r.fish_count),
        })

    out_sessions = []
    for r in sessions.itertuples():
        sid = int(r.session_id)
        rec = {
            "date": str(r.date)[:10],
            "start_time": _s(r.start_time),
            "end_time": _s(r.end_time),
            "hours_fished": None if pd.isna(r.hours_fished) else float(r.hours_fished),
            "location_name": _s(r.location_name),
            "latitude": None if pd.isna(r.latitude) else float(r.latitude),
            "longitude": None if pd.isna(r.longitude) else float(r.longitude),
            "weather": _s(r.weather),
            "air_temp": None if pd.isna(r.air_temp) else float(r.air_temp),
            "water_temp": None if pd.isna(r.water_temp) else float(r.water_temp),
            "bait_lure": _s(r.bait_lure),
            "fishing_style": _s(r.fishing_style),
            "num_anglers": None if pd.isna(r.num_anglers) else int(r.num_anglers),
            "dwr_filed": int(bool(r.dwr_filed)),
            "dwr_filed_at": _s(r.dwr_filed_at),
            "notes": _s(r.notes),
            "moon_phase": _s(r.moon_phase),
            "fish": by_sid_fish.get(sid, []),
            "spots": by_sid_spots.get(sid, []),
        }
        out_sessions.append(rec)

    return {
        "format": "fishing-log-backup",
        "version": BACKUP_VERSION,
        "exported_at": _date.today().isoformat(),
        "session_count": len(out_sessions),
        "fish_count": int(len(fish)),
        "sessions": out_sessions,
    }


def build_zip_bytes() -> bytes:
    """One ZIP with the three CSVs plus the restorable backup.json."""
    data = export_backup()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sessions.csv", _sessions_df().to_csv(index=False))
        zf.writestr("fish.csv", _fish_df().to_csv(index=False))
        zf.writestr("spots.csv", _spots_df().to_csv(index=False))
        zf.writestr(JSON_NAME, json.dumps(data, indent=1, default=str))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def parse_backup(raw: bytes) -> dict:
    """Accept either backup.json bytes or a full backup ZIP; return the dict.

    Raises ValueError with a friendly message on anything unrecognizable.
    """
    if raw[:2] == b"PK":  # ZIP magic
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                name = JSON_NAME if JSON_NAME in zf.namelist() else None
                if name is None:
                    raise ValueError(f"ZIP does not contain {JSON_NAME}.")
                raw = zf.read(name)
        except zipfile.BadZipFile as exc:
            raise ValueError("File looks like a ZIP but could not be read.") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Not a valid backup file (expected backup.json or the backup ZIP).") from exc
    if not isinstance(data, dict) or data.get("format") != "fishing-log-backup":
        raise ValueError("Not a Fishing Log backup file.")
    if not isinstance(data.get("sessions"), list):
        raise ValueError("Backup file has no sessions list.")
    return data


def _existing_keys() -> set:
    q = text("SELECT date, start_time, location_name FROM sessions WHERE user_email = :email")
    with db.get_engine().connect() as conn:
        rows = conn.execute(q, {"email": db.get_current_user()}).mappings().all()
    return {
        (str(r["date"])[:10], r["start_time"] or "", r["location_name"] or "")
        for r in rows
    }


def restore_backup(data: dict, skip_duplicates: bool = True) -> dict:
    """Insert every session in the backup for the current user.

    A "duplicate" is an existing trip with the same date + start time +
    location. Each restored trip goes through data_entry.add_session (full
    validation). dwr_filed is preserved; the dwr_filed_at date is restored
    when present. Returns {"restored": n, "skipped": n, "errors": [msg, ...]}.
    """
    from . import data_entry  # local import to avoid a cycle at module load

    existing = _existing_keys() if skip_duplicates else set()
    restored = skipped = 0
    errors = []

    for i, s in enumerate(data.get("sessions", []), 1):
        key = (str(s.get("date"))[:10], s.get("start_time") or "", s.get("location_name") or "")
        if skip_duplicates and key in existing:
            skipped += 1
            continue
        session = {k: s.get(k) for k in (
            "date", "start_time", "end_time", "hours_fished", "location_name",
            "latitude", "longitude", "weather", "air_temp", "water_temp",
            "bait_lure", "fishing_style", "num_anglers", "dwr_filed",
            "notes", "moon_phase",
        )}
        fish = s.get("fish") or []
        spots = s.get("spots") or []
        try:
            sid = data_entry.add_session(session, fish, spots)
            filed_at = s.get("dwr_filed_at")
            if s.get("dwr_filed") and filed_at:
                with db.get_engine().begin() as conn:
                    conn.execute(
                        text("UPDATE sessions SET dwr_filed_at = :d "
                             "WHERE id = :id AND user_email = :email"),
                        {"d": str(filed_at)[:10], "id": sid,
                         "email": db.get_current_user()},
                    )
            restored += 1
            existing.add(key)
        except Exception as exc:  # keep going; report at the end
            errors.append(f"Trip {i} ({s.get('date')}): {exc}")

    return {"restored": restored, "skipped": skipped, "errors": errors}
