"""Analytics: summary tables of fishing success by various dimensions.

Every function returns a pandas DataFrame so the Streamlit layer can render
sortable tables and charts. "Success rate" = share of sessions that landed at
least one fish.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import database as db

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}
SEASON_ORDER = ["Spring", "Summer", "Fall", "Winter"]


def _session_frame() -> pd.DataFrame:
    """One row per session with total_fish, caught flag, month/season, etc."""
    from sqlalchemy import text
    query = text("""
        SELECT
            s.id, s.date, s.location_name, s.weather, s.hours_fished,
            s.water_temp, s.fishing_style, s.bait_lure, s.start_time,
            s.moon_phase,
            COUNT(f.id) AS total_fish
        FROM sessions s
        LEFT JOIN fish f ON f.session_id = s.id
        WHERE s.user_email = :email
        GROUP BY s.id
    """)
    with db.get_engine().connect() as conn:
        df = pd.read_sql_query(query, conn, params={"email": db.get_current_user()})

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["year"] = df["date"].dt.year
    df["month_num"] = df["date"].dt.month
    df["month"] = df["date"].dt.strftime("%B")
    df["season"] = df["month_num"].map(SEASON_BY_MONTH)
    df["caught"] = df["total_fish"] > 0
    df["hours_fished"] = pd.to_numeric(df["hours_fished"], errors="coerce")
    df["water_temp"] = pd.to_numeric(df["water_temp"], errors="coerce")
    return df


def _summarize(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Common success/productivity metrics grouped by ``group_col``."""
    grouped = df.groupby(group_col, dropna=False)
    out = grouped.agg(
        sessions=("id", "count"),
        sessions_with_fish=("caught", "sum"),
        total_fish=("total_fish", "sum"),
        total_hours=("hours_fished", "sum"),
    ).reset_index()

    out["success_rate_%"] = (out["sessions_with_fish"] / out["sessions"] * 100).round(1)
    out["avg_fish_per_session"] = (out["total_fish"] / out["sessions"]).round(2)
    out["fish_per_hour"] = out.apply(
        lambda r: round(r["total_fish"] / r["total_hours"], 2) if r["total_hours"] else 0.0,
        axis=1,
    )
    out["sessions_with_fish"] = out["sessions_with_fish"].astype(int)
    return out


def by_time_of_year(period: str = "month") -> pd.DataFrame:
    """Success metrics by ``month`` (default) or ``season``."""
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()

    if period == "season":
        out = _summarize(df, "season")
        out["season"] = pd.Categorical(out["season"], categories=SEASON_ORDER, ordered=True)
        return out.sort_values("season").reset_index(drop=True)

    out = _summarize(df, "month")
    out["month"] = pd.Categorical(out["month"], categories=MONTH_ORDER, ordered=True)
    return out.sort_values("month").reset_index(drop=True)


def available_years() -> list:
    """Distinct years present in the data, newest first."""
    df = _session_frame()
    if df.empty:
        return []
    years = df["year"].dropna().astype(int).unique().tolist()
    return sorted(years, reverse=True)


def by_month(year: Optional[int] = None) -> pd.DataFrame:
    """Per-month metrics for one year, with all 12 months present.

    Months without trips are filled with zeros so month-to-month variance is
    visible in a chart. If ``year`` is None, aggregates across all years.
    """
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    if year is not None:
        df = df[df["year"] == year]

    cols = ["month", "sessions", "sessions_with_fish", "total_fish",
            "total_hours", "success_rate_%", "avg_fish_per_session", "fish_per_hour"]
    out = _summarize(df, "month") if not df.empty else pd.DataFrame(columns=cols)

    out = out.set_index("month").reindex(MONTH_ORDER)
    for c in ["sessions", "sessions_with_fish", "total_fish"]:
        out[c] = out[c].fillna(0).astype(int)
    for c in ["total_hours", "success_rate_%", "avg_fish_per_session", "fish_per_hour"]:
        out[c] = out[c].fillna(0.0)
    return out.reset_index()


def by_location() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "location_name")
    return out.sort_values("success_rate_%", ascending=False).reset_index(drop=True)


def by_weather() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "weather")
    return out.sort_values("success_rate_%", ascending=False).reset_index(drop=True)


# --- "What's working" condition insights -----------------------------------

WATER_BANDS = [
    (None, 50, "<50°"), (50, 55, "50–55°"), (55, 60, "55–60°"),
    (60, 65, "60–65°"), (65, 70, "65–70°"), (70, 75, "70–75°"),
    (75, None, "75°+"),
]
WATER_BAND_ORDER = [b[2] for b in WATER_BANDS] + ["Unknown"]

TOD_BANDS = [
    (4, 7, "Dawn (4–7)"), (7, 11, "Morning (7–11)"), (11, 15, "Midday (11–3)"),
    (15, 18, "Afternoon (3–6)"), (18, 21, "Evening (6–9)"),
]
TOD_ORDER = [b[2] for b in TOD_BANDS] + ["Night", "Unknown"]


def _water_band(t) -> str:
    if t is None or pd.isna(t):
        return "Unknown"
    for lo, hi, label in WATER_BANDS:
        if (lo is None or t >= lo) and (hi is None or t < hi):
            return label
    return "Unknown"


def _tod_band(start_time) -> str:
    if not start_time:
        return "Unknown"
    try:
        hour = int(str(start_time).split(":")[0])
    except (ValueError, IndexError):
        return "Unknown"
    for lo, hi, label in TOD_BANDS:
        if lo <= hour < hi:
            return label
    return "Night"


def _ordered(out: pd.DataFrame, col: str, order: list) -> pd.DataFrame:
    out[col] = pd.Categorical(out[col], categories=order, ordered=True)
    return out.sort_values(col).reset_index(drop=True)


def by_water_temp() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    df["water_band"] = df["water_temp"].map(_water_band)
    return _ordered(_summarize(df, "water_band"), "water_band", WATER_BAND_ORDER)


def by_time_of_day() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    df["tod"] = df["start_time"].map(_tod_band)
    return _ordered(_summarize(df, "tod"), "tod", TOD_ORDER)


def by_fishing_style() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "fishing_style")
    return out.sort_values("fish_per_hour", ascending=False).reset_index(drop=True)


def by_bait() -> pd.DataFrame:
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    df = df[df["bait_lure"].astype(str).str.strip() != ""]
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "bait_lure")
    return out.sort_values("fish_per_hour", ascending=False).reset_index(drop=True)


def best_conditions(min_sessions: int = 2) -> list:
    """Top-performing category in each dimension by fish/hour (needs >= min trips).

    Returns a list of (dimension, label, fish_per_hour). Categories with too few
    trips are ignored so a single lucky outing doesn't dominate.
    """
    dims = [
        ("Water temp", by_water_temp(), "water_band"),
        ("Weather", by_weather(), "weather"),
        ("Time of day", by_time_of_day(), "tod"),
        ("Fishing style", by_fishing_style(), "fishing_style"),
        ("Bait / lure", by_bait(), "bait_lure"),
    ]
    results = []
    for name, tbl, col in dims:
        if tbl.empty:
            continue
        eligible = tbl[tbl["sessions"] >= min_sessions]
        pool = eligible if not eligible.empty else tbl
        pool = pool[pool["fish_per_hour"] > 0]
        if pool.empty:
            continue
        top = pool.loc[pool["fish_per_hour"].idxmax()]
        label = top[col]
        if label in (None, "Unknown") or pd.isna(label):
            continue
        results.append((name, str(label), float(top["fish_per_hour"])))
    return results


def by_species() -> pd.DataFrame:
    """Per-species totals plus size metrics (averages ignore unrecorded 0 sizes)."""
    from sqlalchemy import text
    query = text("""
        SELECT
            f.species,
            COUNT(*) AS total_caught,
            COUNT(DISTINCT f.session_id) AS sessions_present,
            ROUND(AVG(NULLIF(f.length, 0))::numeric, 2) AS avg_length,
            MAX(f.length) AS max_length,
            ROUND(AVG(NULLIF(f.weight, 0))::numeric, 2) AS avg_weight,
            MAX(f.weight) AS max_weight
        FROM fish f JOIN sessions s ON s.id = f.session_id
        WHERE s.user_email = :email
        GROUP BY f.species
    """)
    with db.get_engine().connect() as conn:
        df = pd.read_sql_query(query, conn, params={"email": db.get_current_user()})

    if df.empty:
        return df

    df["avg_per_session"] = (df["total_caught"] / df["sessions_present"]).round(2)
    return df.sort_values("total_caught", ascending=False).reset_index(drop=True)


def _fish_with_dates() -> pd.DataFrame:
    """Every fish joined to its session date (for size analytics)."""
    from sqlalchemy import text
    query = text("""
        SELECT f.species, f.length, f.weight, s.date
        FROM fish f JOIN sessions s ON s.id = f.session_id
        WHERE s.user_email = :email
    """)
    with db.get_engine().connect() as conn:
        df = pd.read_sql_query(query, conn, params={"email": db.get_current_user()})
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def personal_bests() -> pd.DataFrame:
    """Per-species longest and heaviest fish, with the date each was caught."""
    df = _fish_with_dates()
    if df.empty:
        return pd.DataFrame()

    records = []
    for species, g in df.groupby("species"):
        rec = {"species": species}
        gl = g[g["length"] > 0]
        if not gl.empty:
            top = gl.loc[gl["length"].idxmax()]
            rec["longest_in"] = round(float(top["length"]), 1)
            rec["longest_date"] = top["date"].date().isoformat()
        else:
            rec["longest_in"], rec["longest_date"] = None, None
        gw = g[g["weight"] > 0]
        if not gw.empty:
            top = gw.loc[gw["weight"].idxmax()]
            rec["heaviest_lb"] = round(float(top["weight"]), 2)
            rec["heaviest_date"] = top["date"].date().isoformat()
        else:
            rec["heaviest_lb"], rec["heaviest_date"] = None, None
        records.append(rec)
    return pd.DataFrame(records).sort_values("species").reset_index(drop=True)


def size_by_month(year: Optional[int] = None) -> pd.DataFrame:
    """Average and max length/weight per month (zeros = unrecorded, ignored)."""
    df = _fish_with_dates()
    if df.empty:
        return pd.DataFrame()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.strftime("%B")
    if year is not None:
        df = df[df["year"] == year]

    def _agg(g):
        lengths = g.loc[g["length"] > 0, "length"]
        weights = g.loc[g["weight"] > 0, "weight"]
        return pd.Series({
            "fish": len(g),
            "avg_length": round(lengths.mean(), 1) if len(lengths) else 0.0,
            "max_length": round(lengths.max(), 1) if len(lengths) else 0.0,
            "avg_weight": round(weights.mean(), 2) if len(weights) else 0.0,
            "max_weight": round(weights.max(), 2) if len(weights) else 0.0,
        })

    if df.empty:
        out = pd.DataFrame(columns=["month", "fish", "avg_length", "max_length", "avg_weight", "max_weight"])
    else:
        out = df.groupby("month").apply(_agg, include_groups=False).reset_index()
    out = out.set_index("month").reindex(MONTH_ORDER).fillna(0.0)
    out["fish"] = out["fish"].astype(int)
    return out.reset_index()


def fish_sizes(year: Optional[int] = None) -> pd.DataFrame:
    """Individual fish (length/weight/species/date) for distribution charts."""
    df = _fish_with_dates()
    if df.empty:
        return df
    df["year"] = df["date"].dt.year
    if year is not None:
        df = df[df["year"] == year]
    return df.reset_index(drop=True)


MOON_ORDER = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]


def by_moon_phase() -> pd.DataFrame:
    """Success metrics grouped by moon phase."""
    df = _session_frame()
    if df.empty or "moon_phase" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["moon_phase"])
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "moon_phase")
    out = _ordered(out, "moon_phase", MOON_ORDER)
    return out


def year_over_year() -> pd.DataFrame:
    """Per-calendar-year totals: trips, fish, success rate, hours."""
    df = _session_frame()
    if df.empty:
        return pd.DataFrame()
    out = _summarize(df, "year").sort_values("year", ascending=False)
    out["year"] = out["year"].astype(int)
    return out[["year", "sessions", "total_fish", "success_rate_%", "total_hours"]]


def overall_stats() -> dict:
    """Headline numbers for the dashboard."""
    df = _session_frame()
    if df.empty:
        return {
            "sessions": 0, "total_fish": 0, "success_rate": 0.0,
            "total_hours": 0.0, "biggest_length": 0.0,
        }
    fish = _fish_with_dates()
    biggest = 0.0
    if not fish.empty and float(fish["length"].max()) > 0:
        biggest = round(float(fish["length"].max()), 1)
    return {
        "sessions": int(len(df)),
        "total_fish": int(df["total_fish"].sum()),
        "success_rate": round(df["caught"].mean() * 100, 1),
        "total_hours": round(df["hours_fished"].fillna(0).sum(), 1),
        "biggest_length": biggest,
    }
