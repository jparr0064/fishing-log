"""Fishing Log — Streamlit app entry point.

Run with:  streamlit run app.py

A thin presentation layer over the ``fishing_log`` package: every page
delegates data work to database / data_entry / search / analytics / map_view.
"""
from __future__ import annotations

import calendar as _cal
import os
from datetime import date, datetime

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from fishing_log import (
    analytics, data_entry, database as db, dwr_report, map_view, search,
)

# Optional GPS button component; app still works if it isn't installed.
try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:  # pragma: no cover
    streamlit_geolocation = None

st.set_page_config(page_title="Fishing Log", page_icon="🎣", layout="wide")

# Default home water — pre-fills the Log a Session form.
DEFAULT_LOCATION = "Smith Mountain Lake"
DEFAULT_LAT = 37.16463
DEFAULT_LON = -79.70913

# The only species this log tracks.
SPECIES = ["Striper", "Largemouth Bass", "Smallmouth Bass", "Catfish", "Muskie"]

# Default "From" date for Map and Browse filters — start of year so all trips show.
DEFAULT_FROM_DATE = date(2026, 1, 1)

# Okabe-Ito color-blind-safe palette (distinguishable across CVD types).
CB_PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442"]


def _inject_css():
    """App-wide polish: card-style metrics, tidy spacing, header accents."""
    st.markdown(
        """
        <style>
          .block-container { padding-top: 2rem; max-width: 1180px; }
          [data-testid="stMetric"] {
            background: #ffffff; border: 1px solid #d7e2ec; border-radius: 12px;
            padding: 12px 16px; box-shadow: 0 1px 2px rgba(16,42,67,.05);
          }
          [data-testid="stMetricValue"] { color: #0e7490; font-weight: 700; }
          [data-testid="stMetricLabel"] { opacity: .75; }
          h1, h2, h3 { color: #0f3a4d; }
          .hero {
            background: linear-gradient(90deg, #0e7490, #0f3a4d);
            border-radius: 14px; padding: 18px 24px; margin-bottom: 16px;
            display: flex; align-items: center; justify-content: space-between;
            flex-wrap: wrap; gap: 16px;
          }
          .hero-title { color: #fff; font-size: 1.5rem; font-weight: 700; line-height: 1.2; }
          .hero-loc { color: #fff; font-size: 1.1rem; font-weight: 600; margin-top: 6px; letter-spacing: .02em; }
          .hero-stats { display: flex; gap: 10px; }
          .hero-chip {
            background: rgba(255,255,255,.15); border-radius: 10px;
            padding: 8px 16px; text-align: center; min-width: 62px;
          }
          .hero-chip .n { display: block; color: #fff; font-size: 1.25rem; font-weight: 700; line-height: 1.1; }
          .hero-chip .l {
            display: block; color: #cdeef0; font-size: .7rem;
            text-transform: uppercase; letter-spacing: .4px;
          }
          .trip-meta { color: #51606b; font-size: .88rem; line-height: 1.5; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _hero_banner():
    """Top-of-app hero: title + current-year trips/fish + all-time personal best."""
    curr_yr = date.today().year
    yoy = analytics.year_over_year()
    yr_row = yoy[yoy["year"] == curr_yr] if not yoy.empty else None
    trips = int(yr_row["sessions"].iloc[0]) if yr_row is not None and not yr_row.empty else 0
    fish  = int(yr_row["total_fish"].iloc[0]) if yr_row is not None and not yr_row.empty else 0
    stats = analytics.overall_stats()
    best  = _fmt_len(stats.get("biggest_length")) or "—"
    st.markdown(
        f"""
        <div class='hero'>
          <div>
            <div class='hero-title'>🎣 Fishing Log</div>
            <div class='hero-loc'>📍 Smith Mountain Lake</div>
          </div>
          <div class='hero-stats'>
            <div class='hero-chip'><span class='n'>{trips}</span><span class='l'>{curr_yr} trips</span></div>
            <div class='hero-chip'><span class='n'>{fish}</span><span class='l'>{curr_yr} fish</span></div>
            <div class='hero-chip'><span class='n'>{best}</span><span class='l'>all-time best</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _fmt_len(value) -> str:
    """Format a length as e.g. 31\" or 24.5\" (blank if none/zero)."""
    if value in (None, "", 0, 0.0):
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    if f != f or f == 0:  # NaN check (NaN != NaN)
        return ""
    return (str(int(f)) if f == int(f) else str(f)) + '"'

# Display labels for the session columns shown in tables.
SESSION_DISPLAY_COLS = {
    "date": "Date",
    "location_name": "Location",
    "start_time": "Start",
    "end_time": "End",
    "hours_fished": "Hours",
    "total_fish": "Fish",
    "species_list": "Species (count)",
    "weather": "Weather",
    "air_temp": "Air °",
    "water_temp": "Water °",
    "bait_lure": "Bait/Lure",
    "fishing_style": "Style",
}


def _oidc_active() -> bool:
    """True when OIDC auth (st.login/st.user) is configured and usable.

    Accessing st.user.is_logged_in raises unless an [auth] block is configured
    in secrets, and st.user may not exist on older Streamlit builds. Treat ANY
    failure as "not active" and fall back to the local email form — otherwise
    the whole app crashes on load (as it did on Streamlit Cloud without [auth]).
    """
    try:
        _ = _st_user().is_logged_in
        return True
    except Exception:
        return False


def _st_user():
    """The signed-in-user object under either of its names.

    Streamlit 1.42 shipped native auth as st.experimental_user; it was renamed
    to st.user in 1.44. The deployed app pins 1.42 (layout), local dev runs
    newer — support both.
    """
    try:
        return st.user
    except AttributeError:
        return st.experimental_user


def _show_login_page(oidc: bool) -> None:
    """Render the sign-in / demo landing page."""
    st.markdown("## 🎣 Fishing Log")
    if oidc:
        st.markdown("Sign in with your Google account to access your fishing log.")
        c1, c2 = st.columns([2, 1])
        if c1.button("Sign in with Google", type="primary"):
            st.login("google")
        if c2.button("Try the Demo →"):
            st.session_state.user_email = DEMO_EMAIL
            st.rerun()
    else:
        st.markdown("Enter your email to get started. Your data is private to you.")
        with st.form("login_form"):
            email = st.text_input("Email address")
            c1, c2 = st.columns([2, 1])
            if c1.form_submit_button("Sign in", type="primary"):
                if "@" in email and "." in email:
                    st.session_state.user_email = email.lower().strip()
                    st.rerun()
                else:
                    st.error("Please enter a valid email address.")
            if c2.form_submit_button("Try the Demo →"):
                st.session_state.user_email = DEMO_EMAIL
                st.rerun()


def _allowed_emails() -> set:
    """Approved real-account emails (lowercased). The owner is always allowed.

    Reads the optional `allowed_emails` secret (a list, or a comma-separated
    string). If it's absent, only the owner (`dev_user_email`) can sign in —
    a safe default until you add people.
    """
    raw = st.secrets.get("allowed_emails", [])
    if isinstance(raw, str):
        raw = raw.split(",")
    allowed = {str(e).strip().lower() for e in raw if e and str(e).strip()}
    owner = str(st.secrets.get("dev_user_email", "")).strip().lower()
    if owner:
        allowed.add(owner)
    return allowed


def _is_allowed(email: str) -> bool:
    """Whether this signed-in email may have a real account (approval list)."""
    return email.lower().strip() in _allowed_emails()


def _show_not_approved_page(email: str) -> None:
    """Signed in with Google, but not on the approved list — offer the demo."""
    st.markdown("## 🎣 Fishing Log")
    st.warning(
        f"You're signed in as **{email}**, but that address isn't on the "
        "approved list yet. Ask the owner to add you, then sign in again."
    )
    c1, c2 = st.columns([2, 1])
    if c1.button("👀 Try the Demo instead →"):
        st.session_state.user_email = DEMO_EMAIL
        st.rerun()
    if c2.button("Sign out"):
        st.logout()


def _get_user_email() -> str:
    """Return the current user's email, or stop to show the login screen.

    Three modes:
    - Demo: session_state["user_email"] == DEMO_EMAIL (bypasses auth in all modes)
    - OIDC (production): [auth] is configured in secrets.toml → use st.login/st.user
    - Local dev: no OIDC configured → plain email form
    """
    # Demo shortcut — works regardless of auth mode
    if st.session_state.get("user_email") == DEMO_EMAIL:
        return DEMO_EMAIL

    if _oidc_active():
        if _st_user().is_logged_in:
            email = _st_user().email.lower().strip()
            # Only approved emails get a real account; others see the demo.
            if not _is_allowed(email):
                _show_not_approved_page(email)
                st.stop()
                return ""  # unreachable
            return email
        _show_login_page(oidc=True)
        st.stop()
        return ""  # unreachable

    # Local dev fallback
    if st.session_state.get("user_email"):
        return st.session_state.user_email
    _show_login_page(oidc=False)
    st.stop()
    return ""  # unreachable


DEMO_EMAIL = "demo@fishinglog.demo"


def _is_demo() -> bool:
    return db.get_current_user() == DEMO_EMAIL and not st.session_state.get("demo_admin_toggle")


@st.cache_resource
def _bootstrap():
    """Wire up DATABASE_URL from secrets and initialise the engine once."""
    import os
    if "database_url" in st.secrets:
        os.environ["DATABASE_URL"] = st.secrets["database_url"]
    return True


def _cache_ver() -> int:
    """Per-user cache generation. Bumped on write to invalidate only this
    user's cached reads (unlike st.cache_data.clear(), which nukes everyone)."""
    return st.session_state.get("_cache_ver", 0)


def _refresh():
    """Invalidate this user's cached reads after a write.

    Bumps a per-user version counter that is part of every cache key, so other
    users' cached data is untouched. The ttl on the cached funcs evicts the now-
    orphaned entries. (Previously called st.cache_data.clear(), clearing ALL users.)
    """
    st.session_state["_cache_ver"] = _cache_ver() + 1


# user_email + cache_ver are cache-key parts only; actual scoping is via
# db.get_current_user(). ttl caps how long stale/orphaned entries live.
@st.cache_data(ttl=300)
def _cached_sessions(user_email, date_from, date_to, location, species, cache_ver=0):
    return search.list_sessions(date_from, date_to, location, species)


@st.cache_data(ttl=300)
def _cached_map_rows(user_email, date_from, date_to, location, species, cache_ver=0):
    return search.map_rows(date_from, date_to, location, species)


@st.cache_data(ttl=300)
def _cached_overall_stats(user_email, cache_ver=0):
    return analytics.overall_stats()


@st.cache_data(ttl=300)
def _cached_personal_bests(user_email, cache_ver=0):
    return analytics.personal_bests()


@st.cache_data(ttl=300)
def _cached_year_over_year(user_email, cache_ver=0):
    return analytics.year_over_year()


@st.cache_data(ttl=300)
def _cached_by_month(user_email, year, cache_ver=0):
    return analytics.by_month(year)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page_dashboard():
    st.header("🎣 Dashboard")
    user = db.get_current_user()
    ver = _cache_ver()
    stats = _cached_overall_stats(user, ver)
    if stats["sessions"] == 0:
        st.info("No sessions yet. Add your first trip under **Log a Session**.")
        return

    # Headline KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trips logged", stats["sessions"])
    c2.metric("Total fish", stats["total_fish"])
    c3.metric("Success rate", f"{stats['success_rate']}%")
    c4.metric("Hours fished", stats["total_hours"])

    # Personal bests at a glance
    best = _cached_personal_bests(user, ver)
    if not best.empty:
        measured = best.dropna(subset=["longest_in"])
        heaviest = best.dropna(subset=["heaviest_lb"])
        b1, b2 = st.columns(2)
        if not measured.empty:
            top = measured.loc[measured["longest_in"].idxmax()]
            b1.metric("🏆 Longest fish", f'{top["longest_in"]}"',
                      f'{top["species"]} · {top["longest_date"]}')
        if not heaviest.empty:
            top = heaviest.loc[heaviest["heaviest_lb"].idxmax()]
            b2.metric("🏆 Heaviest fish", f'{top["heaviest_lb"]} lb',
                      f'{top["species"]} · {top["heaviest_date"]}')

    # Year-over-year snapshot
    yoy = _cached_year_over_year(user, ver)
    if not yoy.empty:
        from datetime import date as _dt
        curr_yr = _dt.today().year
        prev_yr = curr_yr - 1

        def _yr(yr, col):
            row = yoy[yoy["year"] == yr]
            return int(row[col].iloc[0]) if not row.empty else 0

        c_trips = _yr(curr_yr, "sessions")
        c_fish  = _yr(curr_yr, "total_fish")
        p_trips = _yr(prev_yr, "sessions")
        p_fish  = _yr(prev_yr, "total_fish")

        st.subheader("📅 Year over year")
        y1, y2, y3, y4 = st.columns(4)
        y1.metric(f"{curr_yr} trips", c_trips,
                  delta=f"{c_trips - p_trips:+d}" if p_trips or c_trips else None)
        y2.metric(f"{curr_yr} fish",  c_fish,
                  delta=f"{c_fish - p_fish:+d}" if p_fish or c_fish else None)
        y3.metric(f"{prev_yr} trips", p_trips)
        y4.metric(f"{prev_yr} fish",  p_fish)

    # DWR filing nudge
    all_df = _cached_sessions(user, None, None, None, None, cache_ver=ver)
    if not all_df.empty and "dwr_filed" in all_df.columns:
        unfiled = all_df[~all_df["dwr_filed"].fillna(0).astype(bool)]
        if not unfiled.empty:
            with st.container(border=True):
                st.markdown(f"**📋 {len(unfiled)} trip(s) not yet filed to DWR**")
                st.caption("Open a trip in **Browse & Search** to file its striper "
                           "report, then check **Filed to DWR**. Unfiled: "
                           + ", ".join(unfiled["date"].astype(str).head(8))
                           + ("…" if len(unfiled) > 8 else ""))

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Fish per month")
        years = analytics.available_years()
        year = years[0] if years else None
        monthly = _cached_by_month(user, year, ver)
        if not monthly.empty:
            st.caption(f"Season {year}")
            st.altair_chart(
                alt.Chart(monthly).mark_bar(color=CB_PALETTE[0]).encode(
                    x=alt.X("month:N", sort=analytics.MONTH_ORDER, title=None),
                    y=alt.Y("total_fish:Q", title="Fish"),
                    tooltip=["month", "total_fish", "sessions"],
                ).properties(height=260, width="container")
            )

    with right:
        st.subheader("Recent trips")
        recent = _cached_sessions(user, None, None, None, None, cache_ver=ver).head(5)
        if recent.empty:
            st.caption("No trips yet.")
        for r in recent.itertuples():
            big = _fmt_len(getattr(r, "biggest_length", None))
            big_txt = f" · biggest {big}" if big else ""
            with st.container(border=True):
                st.markdown(f"**{r.date}** · {r.location_name}")
                st.markdown(
                    f"<span class='trip-meta'>{int(r.total_fish)} fish{big_txt}<br>"
                    f"{r.species_list or 'skunked'}</span>",
                    unsafe_allow_html=True,
                )


def _append_spot(spots: list, lat, lon) -> bool:
    """Add a spot if it differs from the last one. Returns True if added."""
    lat, lon = round(float(lat), 6), round(float(lon), 6)
    if not spots or (spots[-1]["lat"], spots[-1]["lon"]) != (lat, lon):
        spots.append({"lat": lat, "lon": lon})
        return True
    return False


def _clear_spot_state(state_key: str, map_key: str):
    """Drop a picker's spot list and its per-spot checkbox widget state."""
    n = len(st.session_state.get(state_key, []))
    for i in range(n):
        st.session_state.pop(f"{map_key}_c{i}", None)
    st.session_state.pop(state_key, None)


def _spots_picker(state_key: str, map_key: str):
    """Multi-spot map picker (outside any form). Manages a list of
    {lat, lon, caught} in ``st.session_state[state_key]``. Click the map to add
    each spot; check a box to mark it as a catch spot."""
    st.session_state.setdefault(state_key, [])
    spots = st.session_state[state_key]

    # Sync each spot's caught flag from its checkbox state BEFORE drawing the map.
    for i, sp in enumerate(spots):
        ck = f"{map_key}_c{i}"
        if ck not in st.session_state:
            st.session_state[ck] = bool(sp.get("caught"))
        sp["caught"] = bool(st.session_state[ck])

    zoom_key, center_key = f"{map_key}_zoom", f"{map_key}_center"
    default_center = (spots[0]["lat"], spots[0]["lon"]) if spots else (DEFAULT_LAT, DEFAULT_LON)
    view_center = st.session_state.get(center_key, default_center)
    view_zoom = st.session_state.get(zoom_key, 15)

    hdr_col, fs_col = st.columns([5, 1])
    hdr_col.markdown("**Set your spot(s)** — click the map to drop the start pin, then "
                     "click again to add each spot along your troll.")
    fullscreen = fs_col.checkbox("⛶ Full screen", key=f"{map_key}_fs", value=False)
    map_height = 900 if fullscreen else 480

    if fullscreen:
        st.markdown(
            "<style>.block-container{max-width:100%!important;padding-left:1rem!important;"
            "padding-right:1rem!important}</style>",
            unsafe_allow_html=True,
        )

    map_col, side_col = st.columns([5, 1]) if fullscreen else st.columns([4, 1])

    with side_col:
        st.caption(f"{len(spots)} spot(s)")
        if streamlit_geolocation is not None:
            loc = streamlit_geolocation()
            if loc and loc.get("latitude") is not None:
                if _append_spot(spots, loc["latitude"], loc["longitude"]):
                    st.rerun()
        if spots and st.button("↩ Last", key=f"{map_key}_rmlast"):
            st.session_state.pop(f"{map_key}_c{len(spots) - 1}", None)
            spots.pop()
            st.rerun()
        if spots and st.button("🗑 Clear", key=f"{map_key}_clear"):
            for i in range(len(spots)):
                st.session_state.pop(f"{map_key}_c{i}", None)
            spots.clear()
            st.rerun()

    with map_col:
        # Build the map at the saved center/zoom so reinit lands in the right
        # spot. Do NOT pass center= or zoom= as explicit st_folium props — those
        # trigger a map.setView() call after every render, which animates the map
        # and can cause Leaflet to miss the next click event.
        fmap = folium.Map(location=view_center, zoom_start=view_zoom)
        map_view.draw_route(fmap, spots)
        result = st_folium(
            fmap,
            height=map_height,
            use_container_width=True,
            returned_objects=["last_clicked"],
            key=map_key,
        )
        if result and result.get("last_clicked"):
            lc = result["last_clicked"]
            st.session_state[center_key] = (lc["lat"], lc["lng"])
            if _append_spot(spots, lc["lat"], lc["lng"]):
                st.toast(f"📍 Spot {len(spots)} dropped — click again to add another.")
                st.rerun()

    # Per-spot "fish caught here" toggles.
    if spots:
        st.caption("Mark spots where you caught a fish (shown as a 🐟 on the map):")
        cols = st.columns(min(4, len(spots)))
        for i, sp in enumerate(spots):
            cols[i % len(cols)].checkbox(f"Spot {i + 1} 🎣", key=f"{map_key}_c{i}")
            sp["caught"] = bool(st.session_state[f"{map_key}_c{i}"])


def _blank_fish_df(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "species": [None] * rows, "length": [0.0] * rows,
        "depth": [None] * rows, "weight": [0.0] * rows, "kept": [False] * rows,
    })


def _fish_editor(df: pd.DataFrame, key: str):
    """A data editor with one row per fish: species, length, depth, weight, kept."""
    if "kept" not in df.columns:
        df = df.assign(kept=False)
    if "depth" not in df.columns:
        df = df.assign(depth=None)
    df["kept"] = df["kept"].fillna(False).astype(bool)
    return st.data_editor(
        df, num_rows="dynamic", use_container_width=True,
        column_config={
            "species": st.column_config.SelectboxColumn("Species", options=SPECIES, required=False),
            "length": st.column_config.NumberColumn("Length (in)", min_value=0.0, step=0.5, format="%.1f"),
            "depth": st.column_config.NumberColumn("Depth (ft)", min_value=0.0, step=1.0, format="%.0f",
                                                    help="Depth at which this fish was caught (optional)"),
            "weight": st.column_config.NumberColumn("Weight (lb)", min_value=0.0, step=0.1, format="%.2f"),
            "kept": st.column_config.CheckboxColumn("Kept?", help="Checked = harvested/kept; unchecked = released", default=False),
        },
        column_order=["species", "length", "depth", "weight", "kept"],
        key=key,
    )


def _fish_from_editor(edited: pd.DataFrame) -> list:
    """Extract {species, length, depth, weight, kept} dicts, skipping blank rows."""
    out = []
    for _, r in edited.iterrows():
        sp = r["species"]
        if pd.isna(sp) or not str(sp).strip():
            continue
        length = float(r["length"]) if pd.notna(r.get("length")) else 0.0
        weight = float(r["weight"]) if pd.notna(r.get("weight")) else 0.0
        kept = bool(r["kept"]) if pd.notna(r.get("kept")) else False
        depth_val = r.get("depth")
        depth = float(depth_val) if pd.notna(depth_val) and depth_val else None
        out.append({"species": sp, "length": length, "weight": weight, "kept": kept, "depth": depth})
    return out


def _dwr_nudge(sid: int):
    """DWR filing card shown at the top of Log a Session after saving."""
    detail = search.get_session(sid)
    if not detail:
        return
    report = dwr_report.summarize(detail)
    already_filed = bool(detail.get("dwr_filed"))

    with st.container(border=True):
        hcol, xcol = st.columns([11, 1])
        hcol.markdown(
            f"**📋 DWR Striper Report — {detail['date']} · {detail['location_name']}**  \n"
            f"Harvested: **{report['harvested_n']}** · "
            f"Released: **{report['released_n']}** · "
            f"Anglers: **{report['anglers']}** · "
            f"Hours: **{report['hours'] or '—'}**"
        )
        if xcol.button("✕", key=f"dwr_nx_{sid}", help="Dismiss"):
            st.session_state.pop("pending_dwr_sid", None)
            st.rerun()

        if already_filed:
            st.success("✅ Already filed to DWR — you're all set.")
        else:
            st.caption(
                "Your trip is already saved. "
                "**Step 1:** open the pre-filled form and submit it. "
                "**Step 2:** come back here and click **Mark as filed** so the dashboard clears."
            )
            link_col, btn_col = st.columns([3, 2])
            link_col.link_button(
                "🎣 Step 1 — Open pre-filled DWR form",
                dwr_report.prefilled_url(detail),
                type="primary",
            )
            fk = f"dwr_nf_{sid}"
            if fk not in st.session_state:
                st.session_state[fk] = False

            def _toggle(_sid=sid, _key=fk):
                new_val = st.session_state[_key]
                n = data_entry.set_dwr_filed(_sid, new_val)
                if n == 0:
                    st.session_state.pop(_key, None)
                    st.toast("⚠️ Could not save — try again.", icon="⚠️")
                elif new_val:
                    st.session_state.pop("pending_dwr_sid", None)
                    _refresh()
                else:
                    _refresh()

            btn_col.checkbox("Step 2 — Mark as filed to DWR", key=fk, on_change=_toggle)


def _time_picker(label: str, default_hhmm: str = "06:00", key: str = "") -> str:
    """Renders hour / minute / AM-PM selectors and returns an HH:MM string."""
    try:
        h, m = [int(x) for x in (default_hhmm or "06:00").split(":")]
    except Exception:
        h, m = 6, 0
    ampm_def = "PM" if h >= 12 else "AM"
    h12_def = h % 12 or 12
    m_idx = [0, 15, 30, 45].index(m) if m in (0, 15, 30, 45) else 0

    st.caption(label)
    c1, c2, c3 = st.columns([2, 2, 2])
    hr = c1.selectbox("Hr", list(range(1, 13)), index=h12_def - 1,
                      key=f"{key}_h", label_visibility="collapsed")
    mn = c2.selectbox("Min", [0, 15, 30, 45], index=m_idx,
                      format_func=lambda x: f":{x:02d}",
                      key=f"{key}_m", label_visibility="collapsed")
    ap = c3.selectbox("AM/PM", ["AM", "PM"],
                      index=0 if ampm_def == "AM" else 1,
                      key=f"{key}_ap", label_visibility="collapsed")
    h24 = hr % 12 + (12 if ap == "PM" else 0)
    return f"{h24:02d}:{mn:02d}"


def page_log_session():
    st.header("➕ Log a Session")

    if _is_demo():
        st.warning(
            "This is a read-only demo. Sign in with your own email to log sessions.",
            icon="🔒",
        )
        return

    # Spot picker lives outside the form so map clicks can rerun interactively.
    _spots_picker("spots", "loc_picker")

    # Smart defaults: pre-fill from the most recent session and known baits.
    defaults = search.recent_defaults()
    prev_baits = search.baits_by_frequency()
    last_bait = defaults.get("bait_lure")
    weather_idx = (
        data_entry.WEATHER_OPTIONS.index(defaults["weather"])
        if defaults.get("weather") in data_entry.WEATHER_OPTIONS
        else 0
    )
    style_default = defaults.get("fishing_style") or "Downlines"
    style_idx = (
        data_entry.FISHING_STYLES.index(style_default)
        if style_default in data_entry.FISHING_STYLES
        else 0
    )

    with st.form("session_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            d = st.date_input("Date", value=date.today())
            start_time = _time_picker("Start time", "06:00", "log_start")
            end_time = _time_picker("End time", "11:00", "log_end")
        with col2:
            location_name = st.text_input("Location name", value=DEFAULT_LOCATION)
            num_anglers = st.number_input(
                "Number of anglers", min_value=1, value=1, step=1,
                help="Used for the DWR striper report.",
            )
            n_spots = len(st.session_state.get("spots", []))
            st.caption(
                f"📍 {n_spots} spot(s) set on the map above"
                + ("" if n_spots else f" — defaults to {DEFAULT_LOCATION}")
            )
        with col3:
            weather = st.selectbox("Weather", data_entry.WEATHER_OPTIONS, index=weather_idx)
            # Blank by default — don't invent a reading the angler didn't take.
            air_temp = st.number_input(
                "Air temp (°)", value=None, step=1, format="%d",
                placeholder="optional",
            )
            water_temp = st.number_input(
                "Water temp (°)", value=None, step=1, format="%d",
                placeholder="optional",
            )

        # Bait + style: standard options merged with history; type a new one to add it.
        all_baits = list(dict.fromkeys(data_entry.BAIT_LURE_OPTIONS + prev_baits))
        bcol1, bcol2, bcol3, bcol4 = st.columns(4)
        with bcol1:
            bait_index = (
                all_baits.index(last_bait) if last_bait in all_baits else 0
            )
            bait_choice = st.selectbox(
                "Bait / lure", all_baits, index=bait_index
            )
        with bcol2:
            new_bait = st.text_input("Add new bait / lure")
        with bcol3:
            style_opts = data_entry.FISHING_STYLES
            fishing_style = st.selectbox(
                "Style of fishing", style_opts, index=style_idx
            )
        with bcol4:
            new_style = st.text_input("Add new fishing style")

        notes = st.text_area("Notes", height=80)

        st.markdown("**Fish caught** — one row per fish (species, length, weight). "
                    "Check **Kept?** for harvested fish (vs. released). "
                    "Leave empty if skunked; weight defaults to 0 if unknown.")
        catch_editor = _fish_editor(_blank_fish_df(), key="catch_editor")

        submitted = st.form_submit_button("Save session", type="primary")

    if submitted:
        fish = _fish_from_editor(catch_editor)
        # Spots from the map; fall back to the home lake if none were dropped.
        spots = list(st.session_state.get("spots", [])) or [
            {"lat": DEFAULT_LAT, "lon": DEFAULT_LON}
        ]
        # A typed new value wins; otherwise use the chosen dropdown value.
        bait_lure = new_bait.strip() or bait_choice
        fishing_style = new_style.strip() or fishing_style
        session = {
            "date": d,
            "start_time": start_time,
            "end_time": end_time,
            "location_name": location_name,
            "weather": weather,
            "air_temp": air_temp,
            "water_temp": water_temp,
            "bait_lure": bait_lure,
            "fishing_style": fishing_style,
            "num_anglers": num_anglers,
            "notes": notes,
        }
        try:
            new_id = data_entry.add_session(session, fish, spots)
            _refresh()
            total = len(fish)
            _clear_spot_state("spots", "loc_picker")
            st.session_state["pending_dwr_sid"] = new_id
            st.session_state["log_saved_msg"] = (
                f"✅ Session saved — {total} fish, {len(spots)} spot(s) at {location_name}."
            )
        except data_entry.ValidationError as exc:
            st.error(f"Could not save: {exc}")

    # Show save confirmation + DWR nudge below the form so the form stays
    # ready at the top for the next entry.
    if msg := st.session_state.pop("log_saved_msg", None):
        st.success(msg)
    if "pending_dwr_sid" in st.session_state:
        _dwr_nudge(st.session_state["pending_dwr_sid"])


def _filter_controls(key_prefix: str):
    """Shared date/location/species filter widgets. Returns the filter values."""
    locations = ["", DEFAULT_LOCATION]
    species_opts = [""] + SPECIES
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        date_from = st.date_input("From", value=DEFAULT_FROM_DATE, key=f"{key_prefix}_from")
    with c2:
        date_to = st.date_input("To", value=date.today(), key=f"{key_prefix}_to")
    with c3:
        location = st.selectbox("Location", locations, key=f"{key_prefix}_loc")
    with c4:
        species = st.selectbox("Species", species_opts, key=f"{key_prefix}_sp")
    return (
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
        location or None,
        species or None,
    )


def _trip_card(r):
    """A compact, clickable trip summary card for the Browse grid."""
    selected = st.session_state.get("browse_sel") == int(r.id)
    with st.container(border=True):
        cthumb, cinfo = st.columns([1, 2])
        cthumb.markdown("<div style='font-size:40px;text-align:center'>🎣</div>",
                        unsafe_allow_html=True)
        big = _fmt_len(getattr(r, "biggest_length", None))
        big_txt = f" · biggest {big}" if big else ""
        water = getattr(r, "water_temp", None)
        cond = (getattr(r, "weather", "") or "")
        if water not in (None, ""):
            cond += f" · water {water}°"
        cinfo.markdown(f"**{r.date}** · {r.location_name}")
        cinfo.markdown(
            f"<span class='trip-meta'>{int(r.total_fish)} fish{big_txt}<br>"
            f"{r.species_list or 'skunked'}<br>{cond}</span>",
            unsafe_allow_html=True,
        )
        label = "✓ Viewing" if selected else "View details →"
        if cinfo.button(label, key=f"view_{int(r.id)}", disabled=selected):
            st.session_state["browse_sel"] = int(r.id)
            st.rerun()


def page_browse():
    st.header("🔍 Browse & Search")
    if msg := st.session_state.pop("saved_msg", None):
        st.success(msg)
    df = _cached_sessions(db.get_current_user(), *_filter_controls("browse"), cache_ver=_cache_ver())
    if df.empty:
        st.info("No sessions match these filters.")
        return

    sessions = list(df.itertuples())
    ids = [int(r.id) for r in sessions]
    if st.session_state.get("browse_sel") not in ids:
        st.session_state["browse_sel"] = ids[0]

    for i in range(0, len(sessions), 2):  # 2 cards per row
        cols = st.columns(2)
        for j, r in enumerate(sessions[i:i + 2]):
            with cols[j]:
                _trip_card(r)

    st.divider()
    detail = search.get_session(st.session_state["browse_sel"])
    if detail:
        st.subheader(f"Trip detail — {detail['date']} · {detail['location_name']}")
        _render_session_detail(detail, st.session_state["browse_sel"])


def _render_session_detail(detail: dict, sid: int):
    """Full read/edit detail for one session (used by the Browse cards)."""
    detail_spots = detail.get("spots") or []
    left, right = st.columns(2)
    with left:
        st.write(f"**Date:** {detail['date']}")
        st.write(f"**Location:** {detail['location_name']}")
        st.write(f"**Time:** {detail.get('start_time')} – {detail.get('end_time')} "
                 f"({detail.get('hours_fished')} h)")
        st.write(f"**Spots:** {len(detail_spots)}"
                 + (f" · {sum(bool(s.get('caught')) for s in detail_spots)} with fish"
                    if detail_spots else ""))
    with right:
        st.write(f"**Weather:** {detail.get('weather')}")
        st.write(f"**Air / Water:** {detail.get('air_temp')}° / {detail.get('water_temp')}°")
        st.write(f"**Bait/Lure:** {detail.get('bait_lure')}")
        st.write(f"**Style:** {detail.get('fishing_style') or 'n/a'}")
        st.write(f"**Anglers:** {detail.get('num_anglers') or 1}")
        st.write(f"**Total fish:** {detail['total_fish']}")
        if detail.get("moon_phase"):
            st.write(f"**Moon:** {detail['moon_phase']}")
    if detail["fish"]:
        fish_df = pd.DataFrame(detail["fish"])
        fish_df = fish_df.rename(columns={
            "species": "Species", "length": "Length (in)", "weight": "Weight (lb)",
            "kept": "Kept?", "depth": "Depth (ft)",
        })
        fish_df["Kept?"] = fish_df["Kept?"].apply(lambda x: "✓" if x else "")
        fish_df["Length (in)"] = fish_df["Length (in)"].apply(
            lambda x: "" if not x else (str(int(x)) if float(x) == int(float(x)) else str(x))
        )
        fish_df["Weight (lb)"] = fish_df["Weight (lb)"].apply(
            lambda x: "" if not x else (str(int(x)) if float(x) == int(float(x)) else f"{float(x):.1f}")
        )
        if "Depth (ft)" in fish_df.columns:
            fish_df["Depth (ft)"] = fish_df["Depth (ft)"].apply(
                lambda x: "" if (x is None or (isinstance(x, float) and x != x) or x == 0) else f"{x:.0f}"
            )
        st.table(fish_df)
    if detail.get("notes"):
        st.info(detail["notes"])

    # DWR Striped Bass Angler Journal — pre-filled Google Form for this outing.
    report = dwr_report.summarize(detail)
    with st.container(border=True):
        st.markdown("**📋 DWR Striped Bass Angler Journal**")
        st.caption("Pre-fills the official Google Form for this outing — just review "
                   "and hit Submit. The form collects your email from your Google login.")
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Stripers harvested", report["harvested_n"])
        rc2.metric("Stripers released", report["released_n"])
        rc3.metric("Anglers", report["anglers"])
        st.caption(f"Harvested sizes: {report['harvested_sizes'] or '—'}  •  "
                   f"Released sizes: {report['released_sizes'] or '—'}")
        bcol, fcol = st.columns([2, 2])
        bcol.link_button("🎣 Open pre-filled DWR report",
                         dwr_report.prefilled_url(detail), type="primary")
        fk = f"dwr_filed_{sid}"
        if fk not in st.session_state:
            st.session_state[fk] = bool(detail.get("dwr_filed"))

        def _toggle_filed(_sid=sid, _key=fk):
            n = data_entry.set_dwr_filed(_sid, st.session_state[_key])
            if n == 0:
                st.session_state.pop(_key, None)  # revert display to DB value
                st.toast("⚠️ DWR status could not be saved — try again.", icon="⚠️")
            _refresh()

        fcol.checkbox("✅ Filed to DWR", key=fk, on_change=_toggle_filed,
                      disabled=_is_demo())

    if detail_spots:
        st.markdown(f"**🗺️ Trolling route** ({len(detail_spots)} spot(s)) — "
                    "numbered in order; the arrowed line shows direction; "
                    "🐟 marks where a fish was caught.")
        route_pts = [
            {"lat": s["latitude"], "lon": s["longitude"], "caught": bool(s.get("caught"))}
            for s in detail_spots
        ]
        st_folium(map_view.build_route_map(route_pts), height=320,
                  use_container_width=True, returned_objects=[], key=f"route_{sid}")

    if not _is_demo():
        with st.expander("✏️ Edit this session"):
            skey = f"edit_spots_{sid}"
            if skey not in st.session_state:
                st.session_state[skey] = [
                    {"lat": s["latitude"], "lon": s["longitude"], "caught": bool(s.get("caught"))}
                    for s in detail.get("spots", [])
                ]
            _spots_picker(skey, f"edit_map_{sid}")
            _edit_form(detail)

        if st.button("🗑️ Delete this session", type="secondary", key=f"del_{sid}"):
            data_entry.delete_session(sid)
            _refresh()
            st.session_state.pop("browse_sel", None)
            st.success("Session deleted.")
            st.rerun()


def _edit_form(detail: dict):
    """In-place editor for an existing session (scalar fields + catches).

    Photos are left untouched. Saving calls data_entry.update_session.
    """
    sid = detail["id"]

    def _idx(options, value, default=0):
        return options.index(value) if value in options else default

    # Compute bait list outside the form to avoid DB calls inside form context.
    edit_all_baits = list(dict.fromkeys(
        data_entry.BAIT_LURE_OPTIONS + search.baits_by_frequency()
    ))
    existing_bait = detail.get("bait_lure") or ""
    existing_style = detail.get("fishing_style") or ""

    with st.form(f"edit_form_{sid}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            d = st.date_input(
                "Date", value=datetime.strptime(detail["date"], "%Y-%m-%d").date(),
                key=f"e_date_{sid}",
            )
            start_time = _time_picker(
                "Start time", detail.get("start_time") or "06:00", f"e_start_{sid}"
            )
            end_time = _time_picker(
                "End time", detail.get("end_time") or "11:00", f"e_end_{sid}"
            )
        with c2:
            location_name = st.text_input(
                "Location name", value=detail.get("location_name") or DEFAULT_LOCATION,
                key=f"e_loc_{sid}",
            )
            num_anglers = st.number_input(
                "Number of anglers", min_value=1, step=1,
                value=int(detail.get("num_anglers") or 1), key=f"e_anglers_{sid}",
            )
            n_spots = len(st.session_state.get(f"edit_spots_{sid}", []))
            st.caption(f"📍 {n_spots} spot(s) — edit on the map above")
        with c3:
            weather = st.selectbox(
                "Weather", data_entry.WEATHER_OPTIONS,
                index=_idx(data_entry.WEATHER_OPTIONS, detail.get("weather")),
                key=f"e_weather_{sid}",
            )
            # Keep an existing reading; otherwise blank (don't invent 70/60).
            air_temp = st.number_input(
                "Air temp (°)",
                value=int(float(detail["air_temp"])) if detail.get("air_temp") is not None else None,
                step=1, format="%d", key=f"e_air_{sid}", placeholder="optional",
            )
            water_temp = st.number_input(
                "Water temp (°)",
                value=int(float(detail["water_temp"])) if detail.get("water_temp") is not None else None,
                step=1, format="%d", key=f"e_water_{sid}", placeholder="optional",
            )

        bcol1, bcol2, bcol3, bcol4 = st.columns(4)
        with bcol1:
            bait_choice_e = st.selectbox(
                "Bait / lure", edit_all_baits,
                index=_idx(edit_all_baits, existing_bait),
                key=f"e_bait_{sid}",
            )
        with bcol2:
            new_bait_e = st.text_input(
                "Add new bait / lure", key=f"e_newbait_{sid}"
            )
        with bcol3:
            fishing_style_e = st.selectbox(
                "Style of fishing", data_entry.FISHING_STYLES,
                index=_idx(data_entry.FISHING_STYLES, existing_style),
                key=f"e_style_{sid}",
            )
        with bcol4:
            new_style_e = st.text_input(
                "Add new fishing style", key=f"e_newstyle_{sid}"
            )

        notes = st.text_area("Notes", value=detail.get("notes") or "", key=f"e_notes_{sid}")

        existing = (
            pd.DataFrame(detail["fish"]) if detail["fish"] else _blank_fish_df(1)
        )
        st.markdown("**Fish caught** (one row per fish)")
        catch_editor = _fish_editor(existing, key=f"e_fish_{sid}")

        saved = st.form_submit_button("💾 Save changes", type="primary")

    if saved:
        fish = _fish_from_editor(catch_editor)
        spots = list(st.session_state.get(f"edit_spots_{sid}", []))
        session = {
            "date": d, "start_time": start_time, "end_time": end_time,
            "location_name": location_name,
            "weather": weather, "air_temp": air_temp, "water_temp": water_temp,
            "bait_lure": new_bait_e.strip() or bait_choice_e,
            "fishing_style": new_style_e.strip() or fishing_style_e,
            "num_anglers": num_anglers, "notes": notes,
        }
        try:
            data_entry.update_session(sid, session, fish, spots)
            _refresh()
            # Reset edit state so the expander collapses and reloads fresh.
            _clear_spot_state(f"edit_spots_{sid}", f"edit_map_{sid}")
            st.session_state["saved_msg"] = f"✅ Session #{sid} changes saved."
            st.rerun()
        except data_entry.ValidationError as exc:
            st.error(f"Could not save: {exc}")


def _render_whats_working():
    """Condition insights: which water temp, weather, time, style, bait produce."""
    bests = analytics.best_conditions(min_sessions=2)
    if bests:
        st.markdown("**Your most productive conditions** — ranked by fish per hour")
        cols = st.columns(len(bests))
        for col, (dim, label, fph) in zip(cols, bests):
            col.metric(dim, label, f"{fph} fish/hr")
    else:
        st.caption("Log a few more trips (with conditions filled in) to surface patterns.")

    sections = [
        ("Water temperature", analytics.by_water_temp(), "water_band"),
        ("Weather", analytics.by_weather(), "weather"),
        ("Time of day", analytics.by_time_of_day(), "tod"),
        ("Fishing style", analytics.by_fishing_style(), "fishing_style"),
        ("Bait / lure", analytics.by_bait(), "bait_lure"),
        ("Moon phase", analytics.by_moon_phase(), "moon_phase"),
    ]
    for title, tbl, col in sections:
        if tbl is None or tbl.empty:
            continue
        st.subheader(title)
        show = tbl.rename(columns={
            col: title, "success_rate_%": "success %",
            "fish_per_hour": "fish/hr", "avg_fish_per_session": "avg fish",
        })
        st.dataframe(
            show[[title, "sessions", "success %", "fish/hr", "avg fish"]],
            use_container_width=True, hide_index=True,
        )
        cdf = tbl.copy()
        cdf["cat"] = cdf[col].astype(str)
        st.altair_chart(
            alt.Chart(cdf).mark_bar(color=CB_PALETTE[0]).encode(
                x=alt.X("cat:N", sort=cdf["cat"].tolist(), title=None),
                y=alt.Y("fish_per_hour:Q", title="fish/hr"),
                tooltip=["cat", "sessions", "success_rate_%", "fish_per_hour"],
            ).properties(height=230, width="container")
        )


def page_analytics():
    st.header("📊 Analytics")
    if analytics.overall_stats()["sessions"] == 0:
        st.info("No data yet.")
        return

    years = analytics.available_years()
    year = st.selectbox("Year", years, index=0) if years else None

    tab_month, tab_sizes, tab_best, tab_work = st.tabs(
        ["Monthly", "Sizes", "Personal Bests", "What's working"]
    )

    with tab_work:
        _render_whats_working()

    with tab_month:
        tbl = analytics.by_month(year)
        if tbl.empty:
            st.info("No data for this year.")
        else:
            # Altair fields can't contain '%', so use a chart-friendly copy.
            chart_df = tbl.rename(columns={"success_rate_%": "success_rate"})
            st.subheader(f"Monthly summary — {year}")
            st.dataframe(tbl, use_container_width=True, hide_index=True)

            st.subheader("Fish caught per month")
            st.altair_chart(
                alt.Chart(chart_df).mark_bar(color="#1a9850").encode(
                    x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                    y=alt.Y("total_fish:Q", title="Fish caught"),
                    tooltip=["month", "total_fish", "sessions", "success_rate"],
                ).properties(height=320, width="container")
            )

            st.subheader("Success rate by month (%)")
            st.altair_chart(
                alt.Chart(chart_df).mark_line(point=True, color="#2c7fb8").encode(
                    x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                    y=alt.Y("success_rate:Q", title="Success rate %",
                            scale=alt.Scale(domain=[0, 100])),
                    tooltip=["month", "success_rate", "sessions_with_fish", "sessions"],
                ).properties(height=280, width="container")
            )

    with tab_sizes:
        sizes = analytics.size_by_month(year)
        if sizes.empty:
            st.info("No size data yet — add length/weight when logging fish.")
        else:
            st.subheader(f"Average & max size by month — {year}")
            st.dataframe(sizes, use_container_width=True, hide_index=True)
            melted = sizes.melt(
                id_vars="month", value_vars=["avg_length", "max_length"],
                var_name="metric", value_name="inches",
            )
            st.altair_chart(
                alt.Chart(melted).mark_line(point=True).encode(
                    x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                    y=alt.Y("inches:Q", title="Length (in)"),
                    color=alt.Color("metric:N", title="",
                                    scale=alt.Scale(range=CB_PALETTE[:2])),
                    tooltip=["month", "metric", "inches"],
                ).properties(height=300, width="container")
            )

            st.subheader("Length distribution (in)")
            fish = analytics.fish_sizes(year)
            fish = fish[fish["length"] > 0] if not fish.empty else fish
            if fish.empty:
                st.caption("No measured lengths yet.")
            else:
                st.altair_chart(
                    alt.Chart(fish).mark_bar(color="#1f78b4").encode(
                        x=alt.X("length:Q", bin=alt.Bin(step=2), title="Length (in)"),
                        y=alt.Y("count()", title="Number of fish"),
                        tooltip=[alt.Tooltip("count()", title="fish")],
                    ).properties(height=300, width="container")
                )

    with tab_best:
        best = analytics.personal_bests()
        if best.empty:
            st.info("No fish recorded yet.")
        else:
            measured = best.dropna(subset=["longest_in"])
            heaviest = best.dropna(subset=["heaviest_lb"])
            c1, c2 = st.columns(2)
            if not measured.empty:
                top = measured.loc[measured["longest_in"].idxmax()]
                c1.metric("🏆 Longest fish", f'{top["longest_in"]}"',
                          f'{top["species"]} · {top["longest_date"]}')
            if not heaviest.empty:
                top = heaviest.loc[heaviest["heaviest_lb"].idxmax()]
                c2.metric("🏆 Heaviest fish", f'{top["heaviest_lb"]} lb',
                          f'{top["species"]} · {top["heaviest_date"]}')
            st.subheader("Bests by species")
            st.dataframe(
                best.rename(columns={
                    "species": "Species", "longest_in": "Longest (in)",
                    "longest_date": "Longest date", "heaviest_lb": "Heaviest (lb)",
                    "heaviest_date": "Heaviest date",
                }),
                use_container_width=True, hide_index=True,
            )


def page_map():
    st.header("🗺️ Map")
    st.caption("Each spot is a dropped pin, color-coded by that trip's catch success: "
               "Skunked (0), Good (1–3), Great (4–6), Blowout (7+).")

    col_a, col_b = st.columns([3, 1])
    with col_b:
        fullscreen = st.checkbox("⛶ Full-screen map", value=False)

    filters = _filter_controls("map")
    df = _cached_map_rows(db.get_current_user(), *filters, cache_ver=_cache_ver())
    if df.empty:
        st.info("No spots match these filters.")
        return

    show_heat = st.checkbox(
        "🔥 Show catch hotspots (heatmap of every spot where you caught a fish)",
        help="Aggregates your trolling catch spots across all matching trips.",
    )
    fmap = map_view.build_map(df)
    if show_heat:
        pts = search.caught_spot_points(*filters)
        if pts:
            map_view.add_heatmap(fmap, pts)
        else:
            st.caption("No catch spots recorded yet — mark spots with 🐟 when logging trips.")

    map_height = 860 if fullscreen else 620
    if fullscreen:
        st.markdown(
            "<style>.block-container{max-width:100%!important;padding-left:1rem!important;"
            "padding-right:1rem!important}</style>",
            unsafe_allow_html=True,
        )
    st_folium(fmap, use_container_width=True, height=map_height, returned_objects=[])

    st.download_button(
        "💾 Download standalone map.html",
        data=fmap.get_root().render(),
        file_name="map.html",
        mime="text/html",
    )


def page_backup():
    st.header("💾 Export")
    st.markdown(
        "Download your data anytime as CSV files — open them in Excel or Google Sheets. "
        "These files are also your backup, so save them somewhere safe periodically."
    )

    sessions_df = search.list_sessions()
    fish_df = search.fish_export()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Sessions** — one row per trip")
        st.caption("Date, location, weather, conditions, hours fished, bait, style, notes.")
        st.download_button(
            "⬇ Download Sessions CSV",
            sessions_df.to_csv(index=False).encode("utf-8"),
            file_name="fishing_sessions.csv",
            mime="text/csv",
            disabled=sessions_df.empty,
            use_container_width=True,
        )
    with c2:
        st.markdown("**Fish** — one row per fish caught")
        st.caption("Species, length, weight, depth, kept/released — linked to each session.")
        st.download_button(
            "⬇ Download Fish CSV",
            fish_df.to_csv(index=False).encode("utf-8"),
            file_name="fishing_fish.csv",
            mime="text/csv",
            disabled=fish_df.empty,
            use_container_width=True,
        )


_MOON_EMOJI = {
    "New Moon": "🌑", "Waxing Crescent": "🌒", "First Quarter": "🌓",
    "Waxing Gibbous": "🌔", "Full Moon": "🌕", "Waning Gibbous": "🌖",
    "Last Quarter": "🌗", "Waning Crescent": "🌘",
}

_CAL_CSS = """
<style>
.fc-wrap{background:#fff;border:1px solid #e0e0e0;border-radius:14px;padding:20px;}
.fc-table{width:100%;border-collapse:collapse;table-layout:fixed;}
.fc-table th{text-align:center;padding:6px 2px;font-size:12px;color:#888;font-weight:600;letter-spacing:.05em;}
.fc-table td{border:1px solid #e8e8e8;vertical-align:top;padding:5px 7px;height:78px;width:14.28%;box-sizing:border-box;}
.fc-table td.other{color:#ccc;}
.fc-table td.caught{background:#e8f5e9;}
.fc-table td.skunked{background:#b8b8b8;}
.fc-table td.today-cell{border:2.5px solid #00695c;}
.day-n{font-weight:600;font-size:13px;display:inline-block;}
.day-n.today-n{background:#00695c;color:#fff;border-radius:50%;width:22px;height:22px;line-height:22px;text-align:center;font-size:12px;}
.moon-e{float:right;font-size:13px;line-height:1;}
.trip-fish{font-size:11px;font-weight:600;color:#2e7d32;margin-top:3px;}
.trip-sk{font-size:11px;font-weight:600;color:#444;margin-top:3px;}
.trip-multi{font-size:10px;color:#555;margin-top:1px;}
.trip-loc{font-size:10px;color:#777;margin-top:1px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}
.fc-legend{display:flex;gap:18px;margin-top:10px;font-size:12px;color:#666;align-items:center;}
.leg-box{width:13px;height:13px;border:1px solid #ccc;display:inline-block;margin-right:4px;vertical-align:middle;border-radius:2px;}
.leg-c{background:#e8f5e9;}.leg-s{background:#b8b8b8;}.leg-n{background:#fff;}
</style>
"""

def _build_calendar_html(year: int, month: int, sessions: dict, today: date) -> str:
    """sessions: {day: [{session_id, total_fish, location, moon_phase}, ...]}"""
    weeks = _cal.Calendar(firstweekday=6).monthdayscalendar(year, month)
    DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
    rows = "<tr>" + "".join(f"<th>{d}</th>" for d in DOW) + "</tr>"
    for week in weeks:
        rows += "<tr>"
        for day in week:
            if day == 0:
                rows += '<td class="other"></td>'
                continue
            is_today = (year == today.year and month == today.month and day == today.day)
            day_sessions = sessions.get(day, [])
            total_fish = sum(s["total_fish"] for s in day_sessions)
            # Cell color: caught if any session had fish; skunked if at least one trip but all zeroes
            cls = "today-cell " if is_today else ""
            if day_sessions:
                cls += "caught" if total_fish > 0 else "skunked"
            rows += f'<td class="{cls}">'
            # Moon from first session of the day
            moon = day_sessions[0]["moon_phase"] if day_sessions else ""
            if moon:
                rows += f'<span class="moon-e">{_MOON_EMOJI.get(moon,"")}</span>'
            num_cls = "day-n today-n" if is_today else "day-n"
            rows += f'<span class="{num_cls}">{day}</span>'
            if day_sessions:
                n = len(day_sessions)
                if n > 1:
                    # Multiple trips — show aggregate
                    rows += f'<div class="trip-fish">🐟 {total_fish} fish</div>'
                    rows += f'<div class="trip-multi">{n} trips</div>'
                else:
                    s = day_sessions[0]
                    if s["total_fish"] > 0:
                        rows += f'<div class="trip-fish">🐟 {s["total_fish"]} fish</div>'
                    else:
                        rows += '<div class="trip-sk">🦨 skunked</div>'
                    rows += f'<div class="trip-loc">{s["location"]}</div>'
            rows += "</td>"
        rows += "</tr>"
    legend = (
        '<div class="fc-legend">'
        '<span><span class="leg-box leg-c"></span>🐟 Caught fish</span>'
        '<span><span class="leg-box leg-s"></span>🦨 Skunked</span>'
        '<span><span class="leg-box leg-n"></span>No trip</span>'
        '</div>'
    )
    return (
        _CAL_CSS
        + '<div class="fc-wrap">'
        + f'<table class="fc-table">{rows}</table>'
        + legend
        + "</div>"
    )


def page_calendar():
    st.header("📅 Calendar")
    today = date.today()

    if "cal_year" not in st.session_state:
        st.session_state.cal_year = today.year
    if "cal_month" not in st.session_state:
        st.session_state.cal_month = today.month

    yr = st.session_state.cal_year
    mo = st.session_state.cal_month

    # Navigation bar
    c_prev, c_yago, c_title, c_today, c_next = st.columns([1, 1.3, 4, 1, 1])
    if c_prev.button("◄ Prev"):
        if mo == 1:
            st.session_state.cal_month, st.session_state.cal_year = 12, yr - 1
        else:
            st.session_state.cal_month = mo - 1
        st.rerun()
    if c_yago.button("📅 Year ago"):
        st.session_state.cal_year = yr - 1
        st.rerun()
    c_title.markdown(
        f"<h3 style='text-align:center;margin:0;padding-top:4px'>"
        f"{_cal.month_name[mo]} {yr}</h3>",
        unsafe_allow_html=True,
    )
    if c_today.button("Today"):
        st.session_state.cal_year, st.session_state.cal_month = today.year, today.month
        st.rerun()
    if c_next.button("Next ►"):
        if mo == 12:
            st.session_state.cal_month, st.session_state.cal_year = 1, yr + 1
        else:
            st.session_state.cal_month = mo + 1
        st.rerun()

    sessions = search.calendar_month(yr, mo)
    st.markdown(_build_calendar_html(yr, mo, sessions, today), unsafe_allow_html=True)

    # Clickable session list below the calendar
    if sessions:
        st.markdown("---")
        st.markdown("**Trips this month** — click a row to read the full session detail.")
        sel = st.session_state.get("cal_sel_sid")
        for day in sorted(sessions.keys()):
            for s in sessions[day]:
                sid = s["session_id"]
                fish_txt = f"🐟 {s['total_fish']} fish" if s["total_fish"] > 0 else "🦨 skunked"
                date_str = f"{yr}-{mo:02d}-{day:02d}"
                label = f"{date_str}  ·  {s['location']}  ·  {fish_txt}"
                btn_label = "▼ Close" if sel == sid else "View →"
                c1, c2 = st.columns([6, 1])
                c1.markdown(label)
                if c2.button(btn_label, key=f"cal_view_{sid}"):
                    st.session_state.cal_sel_sid = None if sel == sid else sid
                    st.rerun()

        sel_sid = st.session_state.get("cal_sel_sid")
        if sel_sid:
            detail = search.get_session(sel_sid)
            if detail:
                st.markdown("---")
                _render_session_detail(detail, sel_sid)


# --------------------------------------------------------------------------
# Sidebar / routing
# --------------------------------------------------------------------------

def main():
    _bootstrap()
    user_email = _get_user_email()   # shows login screen if not signed in
    db.set_current_user(user_email)  # all DB calls in this run are scoped to this user

    # Demo admin: let the dev account edit demo data directly via a sidebar toggle.
    dev_email = st.secrets.get("dev_user_email", "")
    if user_email == dev_email:
        demo_admin = st.sidebar.toggle("🛠 Edit demo data", key="demo_admin_toggle")
        if demo_admin:
            db.set_current_user(DEMO_EMAIL)
    else:
        st.session_state.pop("demo_admin_toggle", None)

    _inject_css()

    st.sidebar.title("🎣 Fishing Log")
    if _is_demo():
        st.sidebar.caption("Viewing **demo data** (read-only)")
    elif st.session_state.get("demo_admin_toggle"):
        st.sidebar.caption(f"🛠 Editing **demo data**")
    else:
        st.sidebar.caption(f"Signed in as **{user_email}**")
    if st.sidebar.button("Sign out"):
        st.session_state.pop("user_email", None)
        if _oidc_active() and _st_user().is_logged_in:
            st.logout()  # clears OIDC cookie and redirects
        else:
            st.rerun()

    if _is_demo():
        st.info(
            "**Demo mode — read only.** You're browsing 15 sample Smith Mountain Lake "
            "striper trips. Sign in with your own email to start logging your catches.",
            icon="ℹ️",
        )
    elif st.session_state.get("demo_admin_toggle"):
        st.warning("🛠 **Demo admin mode** — changes here are live for all demo viewers.", icon="🛠️")

    page = st.sidebar.radio(
        "Navigate",
        ["Dashboard", "Log a Session", "Browse & Search", "Analytics",
         "Calendar", "Map", "Export"],
    )

    _hero_banner()

    st.sidebar.divider()
    n_sessions = db.session_count()
    if n_sessions == 0:
        st.sidebar.info("No sessions yet — add one under **Log a Session**.")
    else:
        st.sidebar.caption(f"{n_sessions} sessions logged.")
        if not _is_demo():
            with st.sidebar.expander("⚠️ Clear my data"):
                st.caption("Deletes ALL your sessions and fish records. Cannot be undone, "
                           "and there is no server-side backup — **download your data first.**")
                # Export-first gate: user must grab a CSV backup before the
                # delete button unlocks.
                sessions_csv = _cached_sessions(
                    db.get_current_user(), None, None, None, None, cache_ver=_cache_ver()
                ).to_csv(index=False).encode("utf-8")
                got_backup = st.download_button(
                    "⬇️ Step 1 — Download my data (CSV)",
                    data=sessions_csv,
                    file_name="fishing_log_backup.csv",
                    mime="text/csv",
                )
                if got_backup:
                    st.session_state["_clear_backup_downloaded"] = True
                downloaded = st.session_state.get("_clear_backup_downloaded", False)
                confirm = st.checkbox(
                    "Step 2 — I've downloaded my backup and want to delete everything",
                    disabled=not downloaded,
                )
                if st.button("Delete all my data", type="primary",
                             disabled=not (downloaded and confirm)):
                    db.delete_all_sessions()
                    _refresh()
                    st.session_state.pop("_clear_backup_downloaded", None)
                    st.success("All your data deleted.")
                    st.rerun()

    {
        "Dashboard": page_dashboard,
        "Log a Session": page_log_session,
        "Browse & Search": page_browse,
        "Analytics": page_analytics,
        "Calendar": page_calendar,
        "Map": page_map,
        "Export": page_backup,
    }[page]()


if __name__ == "__main__":
    main()
