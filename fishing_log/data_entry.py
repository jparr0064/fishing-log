"""Create / update / delete fishing sessions, with validation.

A "session" is the dict of column values for the ``sessions`` table; "fish"
is a list of ``{"species": str, "length": float, "weight": float}`` dicts —
one per fish. Zero fish means a skunked trip.
"""
from __future__ import annotations

from datetime import date as _date, datetime
from typing import List, Optional

from . import database as db


def moon_phase_name(d) -> str:
    """Return the moon phase name for a date. Pure math — works fully offline."""
    if isinstance(d, str):
        d = _date.fromisoformat(d[:10])
    elif isinstance(d, datetime):
        d = d.date()
    known_new = _date(2000, 1, 6)
    days = (d - known_new).days % 29.53058868
    if days < 1.85:   return "New Moon"
    if days < 7.38:   return "Waxing Crescent"
    if days < 9.22:   return "First Quarter"
    if days < 14.77:  return "Waxing Gibbous"
    if days < 16.61:  return "Full Moon"
    if days < 22.15:  return "Waning Gibbous"
    if days < 23.99:  return "Last Quarter"
    return "Waning Crescent"


class ValidationError(ValueError):
    """Raised when a session or catch fails validation."""


WEATHER_OPTIONS = ["Sunny", "Partly Cloudy", "Cloudy", "Overcast", "Rain", "Windy", "Fog", "Snow"]

FISHING_STYLES = ["Planer Boards", "Casting", "Drop Line with Bait", "Spoon Rip Up"]


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValidationError(f"Invalid time '{value}' (expected HH:MM).")


def compute_hours(start_time: Optional[str], end_time: Optional[str]) -> Optional[float]:
    """Hours between start and end (handles crossing midnight). None if missing."""
    start = _parse_time(start_time)
    end = _parse_time(end_time)
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() / 3600.0
    if delta < 0:  # crossed midnight
        delta += 24.0
    return round(delta, 2)


def validate_session(session: dict) -> dict:
    """Validate and normalize a session dict. Returns a cleaned copy."""
    cleaned = dict(session)

    # Date is required and must be ISO-parseable.
    raw_date = cleaned.get("date")
    if not raw_date:
        raise ValidationError("Date is required.")
    if isinstance(raw_date, datetime):
        cleaned["date"] = raw_date.strftime("%Y-%m-%d")
    else:
        try:
            cleaned["date"] = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").strftime(
                "%Y-%m-%d"
            )
        except ValueError as exc:
            raise ValidationError(f"Invalid date '{raw_date}' (expected YYYY-MM-DD).") from exc

    if not cleaned.get("location_name"):
        raise ValidationError("Location name is required.")

    # Times are optional but, if present, must parse.
    _parse_time(cleaned.get("start_time"))
    _parse_time(cleaned.get("end_time"))

    # Auto-compute hours when not supplied.
    if cleaned.get("hours_fished") in (None, "", 0, 0.0):
        computed = compute_hours(cleaned.get("start_time"), cleaned.get("end_time"))
        if computed is not None:
            cleaned["hours_fished"] = computed
    if cleaned.get("hours_fished") is not None:
        if float(cleaned["hours_fished"]) < 0:
            raise ValidationError("Hours fished cannot be negative.")

    lat = cleaned.get("latitude")
    if lat is not None and lat != "":
        if not (-90 <= float(lat) <= 90):
            raise ValidationError("Latitude must be between -90 and 90.")
    lon = cleaned.get("longitude")
    if lon is not None and lon != "":
        if not (-180 <= float(lon) <= 180):
            raise ValidationError("Longitude must be between -180 and 180.")

    na = cleaned.get("num_anglers")
    if na in (None, ""):
        cleaned["num_anglers"] = 1
    else:
        na = int(na)
        if na < 1:
            raise ValidationError("Number of anglers must be at least 1.")
        cleaned["num_anglers"] = na

    cleaned["dwr_filed"] = int(bool(cleaned.get("dwr_filed")))

    if not cleaned.get("moon_phase"):
        cleaned["moon_phase"] = moon_phase_name(cleaned["date"])

    return cleaned


def validate_fish(fish: List[dict]) -> List[dict]:
    """Normalize catch entries into one dict per fish: {species, length, weight}.

    Accepts two input shapes (so older callers/tests keep working):
      * per-fish: {"species", "length", "weight"}  -> one fish
      * legacy aggregate: {"species", "count"}      -> expanded to N fish (0/0)
    Blank-species rows are skipped.
    """
    cleaned = []
    for item in fish or []:
        species = (item.get("species") or "").strip()
        if not species:
            continue
        if "count" in item and "length" not in item and "weight" not in item:
            try:
                count = int(item.get("count", 0))
            except (TypeError, ValueError):
                raise ValidationError(f"Catch count for '{species}' must be a whole number.")
            if count < 0:
                raise ValidationError(f"Catch count for '{species}' cannot be negative.")
            cleaned.extend({"species": species, "length": 0.0, "weight": 0.0} for _ in range(count))
        else:
            try:
                length = float(item.get("length") or 0)
                weight = float(item.get("weight") or 0)
            except (TypeError, ValueError):
                raise ValidationError(f"Length/weight for '{species}' must be numbers.")
            if length < 0 or weight < 0:
                raise ValidationError(f"Length/weight for '{species}' cannot be negative.")
            depth = item.get("depth")
            cleaned.append({
                "species": species, "length": length, "weight": weight,
                "kept": bool(item.get("kept")),
                "depth": float(depth) if depth else None,
            })
    return cleaned


def validate_spots(spots: List[dict]) -> List[dict]:
    """Validate map spots (lat/long bounds). Each item: {lat, lon, label?}."""
    cleaned = []
    for s in spots or []:
        if s.get("lat") is None or s.get("lon") is None:
            continue
        lat, lon = float(s["lat"]), float(s["lon"])
        if not (-90 <= lat <= 90):
            raise ValidationError("Spot latitude must be between -90 and 90.")
        if not (-180 <= lon <= 180):
            raise ValidationError("Spot longitude must be between -180 and 180.")
        cleaned.append({
            "lat": lat, "lon": lon, "label": s.get("label"),
            "caught": bool(s.get("caught")),
        })
    return cleaned


def add_session(
    session: dict, fish: Optional[List[dict]] = None, spots: Optional[List[dict]] = None
) -> int:
    """Validate and persist a session, its fish, and its map spots. Returns new id."""
    from sqlalchemy import text
    cleaned = validate_session(session)
    cleaned_fish = validate_fish(fish or [])
    cleaned_spots = validate_spots(spots or [])
    if cleaned_spots:
        cleaned["latitude"] = cleaned_spots[0]["lat"]
        cleaned["longitude"] = cleaned_spots[0]["lon"]
    session_id = db.insert_session(cleaned)
    db.insert_fish(session_id, cleaned_fish)
    db.insert_spots(session_id, cleaned_spots)
    return session_id


def update_session(
    session_id: int, session: dict,
    fish: Optional[List[dict]] = None, spots: Optional[List[dict]] = None,
) -> None:
    """Replace a session's fields and (entirely) its fish and spots lists."""
    from sqlalchemy import text
    cleaned = validate_session(session)
    cleaned_fish = validate_fish(fish or [])
    cleaned_spots = validate_spots(spots or [])
    if cleaned_spots:
        cleaned["latitude"] = cleaned_spots[0]["lat"]
        cleaned["longitude"] = cleaned_spots[0]["lon"]

    assignments = ", ".join(f"{f} = :{f}" for f in db.SESSION_FIELDS)
    params = {f: cleaned.get(f) for f in db.SESSION_FIELDS}
    params["id"] = session_id

    with db.get_engine().begin() as conn:
        result = conn.execute(
            text(f"UPDATE sessions SET {assignments} WHERE id = :id"),
            params,
        )
        if result.rowcount == 0:
            raise ValidationError(f"No session with id {session_id}.")
        conn.execute(text("DELETE FROM fish WHERE session_id = :sid"), {"sid": session_id})
        if spots is not None:
            conn.execute(text("DELETE FROM spots WHERE session_id = :sid"), {"sid": session_id})

    db.insert_fish(session_id, cleaned_fish)
    if spots is not None:
        db.insert_spots(session_id, cleaned_spots)


def set_dwr_filed(session_id: int, filed: bool) -> int:
    """Mark whether a session's striper report has been filed to DWR.

    Returns the number of rows updated (0 means the session_id wasn't found).
    Scoped to session_id only — user is already authenticated at the app level.
    """
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        result = conn.execute(
            text("UPDATE sessions SET dwr_filed = :filed WHERE id = :id"),
            {"filed": int(bool(filed)), "id": session_id},
        )
        return result.rowcount


def delete_session(session_id: int) -> None:
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM sessions WHERE id = :id"),
            {"id": session_id},
        )
