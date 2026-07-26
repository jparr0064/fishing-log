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

from . import database as db, observability as obs

BACKUP_VERSION = 2          # v2 adds trip_uuid for idempotent restore
SUPPORTED_VERSIONS = (1, 2)  # v1 files restore fine; they just have no uuids
JSON_NAME = "backup.json"

# ---------------------------------------------------------------------------
# Restore limits (CR-7)
#
# The uploaded file is untrusted: it arrives from a user's disk, and a ZIP can
# expand to orders of magnitude more than its compressed size. Every bound is
# enforced while reading, not after — a declared size in a ZIP header is a
# claim, not a fact.
#
# Sized generously against real use. The review's largest test account is 500
# trips; a heavy day is tens of fish, not thousands.
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB as uploaded
MAX_JSON_BYTES = 64 * 1024 * 1024     # 64 MB once decompressed
MAX_COMPRESSION_RATIO = 200           # refuse absurdly compressible archives
MAX_SESSIONS = 20_000
MAX_CHILDREN_PER_SESSION = 5_000      # fish or spots on a single trip

# Values a spreadsheet treats as the start of a formula rather than text.
# Neutralised in CSV exports only — backup.json keeps the raw value, so a
# restore round-trips exactly what was typed.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class BackupError(ValueError):
    """An uploaded backup was rejected. Message is safe to show the user."""


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _sessions_df() -> pd.DataFrame:
    # trip_uuid only exists after migration 003; select it when present so the
    # export works either side of that migration.
    uuid_col = ", trip_uuid" if db.has_trip_uuid_column() else ""
    q = text(f"""
        SELECT id AS session_id, date, start_time, end_time, hours_fished,
               location_name, latitude, longitude, weather, air_temp,
               water_temp, bait_lure, fishing_style, num_anglers,
               dwr_filed, dwr_filed_at, notes, moon_phase{uuid_col}
        FROM sessions WHERE user_email = :email
        ORDER BY date, id
    """)
    with db.read_connection() as conn:
        df = pd.read_sql_query(q, conn, params={"email": db.get_current_user()})
    if "trip_uuid" not in df.columns:
        df["trip_uuid"] = None
    return df


def _fish_df() -> pd.DataFrame:
    q = text("""
        SELECT f.id AS fish_id, f.session_id, s.date, s.location_name,
               f.species, f.length, f.weight, f.kept, f.depth
        FROM fish f JOIN sessions s ON s.id = f.session_id
        WHERE s.user_email = :email
        ORDER BY f.session_id, f.id
    """)
    with db.read_connection() as conn:
        return pd.read_sql_query(q, conn, params={"email": db.get_current_user()})


def _spots_df() -> pd.DataFrame:
    q = text("""
        SELECT sp.id AS spot_id, sp.session_id, s.date,
               sp.latitude, sp.longitude, sp.label, sp.caught, sp.fish_count
        FROM spots sp JOIN sessions s ON s.id = sp.session_id
        WHERE s.user_email = :email
        ORDER BY sp.session_id, sp.id
    """)
    with db.read_connection() as conn:
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


def export_backup(
    sessions: Optional[pd.DataFrame] = None,
    fish: Optional[pd.DataFrame] = None,
    spots: Optional[pd.DataFrame] = None,
) -> dict:
    """The complete restorable record for the current user.

    The three frames can be passed in when the caller already has them, so
    building the ZIP does not query every table twice (CR-5).
    """
    sessions = _sessions_df() if sessions is None else sessions
    fish = _fish_df() if fish is None else fish
    spots = _spots_df() if spots is None else spots

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
            "trip_uuid": _s(getattr(r, "trip_uuid", None)),
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


def neutralize_formula(value):
    """Defuse a value a spreadsheet would execute as a formula.

    A trip note of ``=HYPERLINK("http://evil","Click")`` — or the classic
    ``=cmd|'/c calc'!A1`` — is inert text in the database and in JSON, but
    Excel and Google Sheets evaluate it the moment the CSV is opened. Prefixing
    with an apostrophe forces text interpretation; the apostrophe is not part
    of the value and is not shown in the cell.

    Applied ONLY to CSV output. backup.json keeps the raw value so a restore
    reproduces exactly what the angler typed (CR-7).
    """
    if isinstance(value, str) and value[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def to_safe_csv(df: pd.DataFrame) -> str:
    """CSV text with every text cell defused against formula injection."""
    if df.empty:
        return df.to_csv(index=False)
    from pandas.api import types as pdt

    safe = df.copy()
    for column in safe.columns:
        # Only text columns can carry a leading '='; numeric and boolean ones
        # cannot, and mapping over them would coerce dtypes for nothing.
        #
        # Test both object and string dtypes: pandas 3.0 gave strings their own
        # dtype, so the once-idiomatic `dtype == object` check now matches no
        # text column at all and silently disables this whole defence.
        series = safe[column]
        if pdt.is_object_dtype(series) or pdt.is_string_dtype(series):
            safe[column] = series.map(neutralize_formula)
    return safe.to_csv(index=False)


def build_zip_bytes() -> bytes:
    """One ZIP with the three CSVs plus the restorable backup.json.

    Each table is read exactly once and reused for both the CSV and the JSON.
    This used to query all three twice — once for export_backup() and again
    per CSV — six round trips for three tables' worth of data (CR-5).
    """
    sessions, fish, spots = _sessions_df(), _fish_df(), _spots_df()
    data = export_backup(sessions, fish, spots)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sessions.csv", to_safe_csv(sessions))
        zf.writestr("fish.csv", to_safe_csv(fish))
        zf.writestr("spots.csv", to_safe_csv(spots))
        zf.writestr(JSON_NAME, json.dumps(data, indent=1, default=str))
    payload = buf.getvalue()

    # Audit the event, not its contents: how much moved, never what it said.
    obs.audit("backup.exported", trips=len(sessions), fish=len(fish),
              spots=len(spots), bytes=len(payload), version=BACKUP_VERSION)
    return payload


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _extract_json(raw: bytes) -> bytes:
    """Pull backup.json out of a ZIP without letting it expand unbounded.

    zipfile decompresses on read, so a small archive can claim gigabytes of
    memory. Both the declared size AND the bytes actually read are capped —
    the header is attacker-controlled and can understate the truth.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            if JSON_NAME not in zf.namelist():
                raise BackupError(f"ZIP does not contain {JSON_NAME}.")
            info = zf.getinfo(JSON_NAME)

            if info.file_size > MAX_JSON_BYTES:
                raise BackupError(
                    f"Backup is too large to restore "
                    f"({info.file_size // (1024 * 1024)} MB uncompressed)."
                )
            if info.compress_size and (
                info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
            ):
                raise BackupError(
                    "This archive expands far more than a real backup would, "
                    "so it was not opened."
                )

            with zf.open(JSON_NAME) as handle:
                # One byte past the limit is enough to know it overflowed.
                payload = handle.read(MAX_JSON_BYTES + 1)
            if len(payload) > MAX_JSON_BYTES:
                raise BackupError("Backup is too large to restore.")
            return payload
    except zipfile.BadZipFile as exc:
        raise BackupError("File looks like a ZIP but could not be read.") from exc


def parse_backup(raw: bytes) -> dict:
    """Accept either backup.json bytes or a full backup ZIP; return the dict.

    Raises BackupError (a ValueError) with a friendly message on anything
    unrecognisable, unsupported, or oversized. Nothing here touches the
    database — parsing is entirely separate from writing.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BackupError(
            f"That file is {len(raw) // (1024 * 1024)} MB. The limit is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    if not raw:
        raise BackupError("That file is empty.")

    if raw[:2] == b"PK":  # ZIP magic
        raw = _extract_json(raw)

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(
            "Not a valid backup file (expected backup.json or the backup ZIP)."
        ) from exc

    if not isinstance(data, dict) or data.get("format") != "fishing-log-backup":
        raise BackupError("Not a Fishing Log backup file.")

    # Version is enforced, not merely recorded. An unknown version means the
    # file was written by a build that knows something this one does not —
    # restoring it would drop or misread fields silently.
    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        if isinstance(version, int) and version > BACKUP_VERSION:
            raise BackupError(
                f"This backup is version {version}, but this app understands "
                f"up to version {BACKUP_VERSION}. Update the app, then restore."
            )
        raise BackupError(
            f"Unrecognised backup version ({version!r}). Supported: "
            + ", ".join(str(v) for v in SUPPORTED_VERSIONS) + "."
        )

    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        raise BackupError("Backup file has no sessions list.")
    if len(sessions) > MAX_SESSIONS:
        raise BackupError(
            f"Backup holds {len(sessions):,} trips, above the "
            f"{MAX_SESSIONS:,} limit for a single restore."
        )

    for i, s in enumerate(sessions, 1):
        if not isinstance(s, dict):
            raise BackupError(f"Trip {i} in the backup is not a record.")
        for child in ("fish", "spots"):
            rows = s.get(child)
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise BackupError(f"Trip {i}: '{child}' is not a list.")
            if len(rows) > MAX_CHILDREN_PER_SESSION:
                raise BackupError(
                    f"Trip {i} claims {len(rows):,} {child}, above the "
                    f"{MAX_CHILDREN_PER_SESSION:,} limit."
                )
    return data


def _existing_identity() -> tuple:
    """What the current user already has: (uuids, heuristic keys).

    The uuid set is authoritative. The heuristic — date + start time +
    location — is the fallback for v1 backups and for trips that predate
    migration 003, and it is wrong in both directions: two trips to the same
    spot on the same morning with no start time look identical, while renaming
    a location makes an already-restored trip look new.
    """
    uuid_col = ", trip_uuid" if db.has_trip_uuid_column() else ""
    q = text(f"SELECT date, start_time, location_name{uuid_col} "
             f"FROM sessions WHERE user_email = :email")
    with db.read_connection() as conn:
        rows = conn.execute(q, {"email": db.get_current_user()}).mappings().all()

    uuids = {r["trip_uuid"] for r in rows if r.get("trip_uuid")} if uuid_col else set()
    keys = {
        (str(r["date"])[:10], r["start_time"] or "", r["location_name"] or "")
        for r in rows
    }
    return uuids, keys


def _heuristic_key(s: dict) -> tuple:
    return (str(s.get("date"))[:10], s.get("start_time") or "", s.get("location_name") or "")


_SESSION_KEYS = (
    "date", "start_time", "end_time", "hours_fished", "location_name",
    "latitude", "longitude", "weather", "air_temp", "water_temp",
    "bait_lure", "fishing_style", "num_anglers", "dwr_filed",
    "notes", "moon_phase",
)


def preview_restore(data: dict, skip_duplicates: bool = True) -> dict:
    """Report what a restore would do, WITHOUT writing anything (CR-7).

    Restore is the one operation that can silently double an angler's history,
    and there is no server-side backup to undo it with. Counting first means
    the decision is made with the numbers on screen.

    Returns {"total", "to_restore", "duplicates", "fish", "spots",
             "matched_by": "uuid"|"date+time+location"|"none", "warnings"}.
    """
    sessions = data.get("sessions", [])
    existing_uuids, existing_keys = _existing_identity()

    to_restore = duplicates = fish = spots = 0
    seen_uuids, seen_keys = set(), set()
    matched_by = set()

    for s in sessions:
        uid = s.get("trip_uuid")
        if skip_duplicates:
            if uid and (uid in existing_uuids or uid in seen_uuids):
                duplicates += 1
                matched_by.add("uuid")
                continue
            if not uid:
                key = _heuristic_key(s)
                if key in existing_keys or key in seen_keys:
                    duplicates += 1
                    matched_by.add("date+time+location")
                    continue
        if uid:
            seen_uuids.add(uid)
        else:
            seen_keys.add(_heuristic_key(s))
        to_restore += 1
        fish += len(s.get("fish") or [])
        spots += len(s.get("spots") or [])

    warnings = []
    without_uuid = sum(1 for s in sessions if not s.get("trip_uuid"))
    if without_uuid and skip_duplicates:
        warnings.append(
            f"{without_uuid} trip(s) in this backup have no stable id, so "
            "duplicate detection for them falls back to matching date, start "
            "time and location — which can misjudge two trips to the same spot "
            "on the same day."
        )
    if not db.has_trip_uuid_column():
        warnings.append(
            "This database has not had migration 003 applied, so restored "
            "trips will not get stable ids."
        )

    return {
        "total": len(sessions),
        "to_restore": to_restore,
        "duplicates": duplicates,
        "fish": fish,
        "spots": spots,
        "matched_by": "+".join(sorted(matched_by)) if matched_by else "none",
        "warnings": warnings,
    }


def restore_backup(data: dict, skip_duplicates: bool = True) -> dict:
    """Insert every session in the backup for the current user.

    Duplicate detection prefers the trip's stable id and falls back to
    date + start time + location for v1 backups. Each restored trip is written
    by data_entry.add_session in ONE transaction — full validation, and its
    fish, spots, filed date and stable id all commit together or not at all. A
    trip that fails is reported and the rest continue; a trip that fails leaves
    nothing behind.

    Returns {"restored": n, "skipped": n, "errors": [msg, ...]}.
    """
    from . import data_entry  # local import to avoid a cycle at module load

    if skip_duplicates:
        existing_uuids, existing_keys = _existing_identity()
    else:
        existing_uuids, existing_keys = set(), set()

    restored = skipped = 0
    errors = []

    for i, s in enumerate(data.get("sessions", []), 1):
        uid = s.get("trip_uuid")
        key = _heuristic_key(s)

        if skip_duplicates:
            if uid and uid in existing_uuids:
                skipped += 1
                continue
            if not uid and key in existing_keys:
                skipped += 1
                continue

        session = {k: s.get(k) for k in _SESSION_KEYS}
        try:
            data_entry.add_session(
                session,
                s.get("fish") or [],
                s.get("spots") or [],
                dwr_filed_at=s.get("dwr_filed_at"),
                trip_uuid=uid,
            )
            restored += 1
            if uid:
                existing_uuids.add(uid)
            existing_keys.add(key)
        except Exception as exc:  # keep going; report at the end
            errors.append(f"Trip {i} ({s.get('date')}): {exc}")
            obs.failure("restore.trip_failed",
                        correlation_id=obs.new_correlation_id(), exc=exc,
                        trip_index=i)

    obs.audit("backup.restored", restored=restored, skipped=skipped,
              failed=len(errors), offered=len(data.get("sessions", [])),
              version=data.get("version"), skip_duplicates=skip_duplicates)
    return {"restored": restored, "skipped": skipped, "errors": errors}
