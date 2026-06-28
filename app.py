"""Fishing Log — Streamlit app entry point.

Run with:  streamlit run app.py

A thin presentation layer over the ``fishing_log`` package: every page
delegates data work to database / data_entry / search / analytics / map_view.
"""
from __future__ import annotations

import os
from datetime import date, datetime

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from fishing_log import (
    analytics, backup, data_entry, database as db, dwr_report, map_view, media, search,
)

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    from streamlit_cropper import st_cropper as _st_cropper
    _CROPPER_OK = True
except Exception:
    _CROPPER_OK = False

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

# Default "From" date for Map and Browse filters (first log).
DEFAULT_FROM_DATE = date(2026, 6, 7)

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
          .hero-sub { color: #cdeef0; font-size: .9rem; margin-top: 3px; }
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
    """Top-of-app hero: title + at-a-glance season stats (trips / fish / best)."""
    stats = analytics.overall_stats()
    best = _fmt_len(stats.get("biggest_length")) or "—"
    st.markdown(
        f"""
        <div class='hero'>
          <div>
            <div class='hero-title'>🎣 Fishing Log</div>
            <div class='hero-sub'>Smith Mountain Lake &middot; striper trolling</div>
          </div>
          <div class='hero-stats'>
            <div class='hero-chip'><span class='n'>{stats['sessions']}</span><span class='l'>trips</span></div>
            <div class='hero-chip'><span class='n'>{stats['total_fish']}</span><span class='l'>fish</span></div>
            <div class='hero-chip'><span class='n'>{best}</span><span class='l'>best</span></div>
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


def _get_user_email() -> str:
    """Get the logged-in user's email. Uses Streamlit viewer auth on Cloud,
    falls back to a simple email form for local development."""
    # Streamlit Community Cloud viewer auth (set via app settings → Viewer auth)
    try:
        user = st.experimental_user
        if user and getattr(user, "email", None):
            return user.email.lower().strip()
    except Exception:
        pass

    # Local dev fallback: simple one-time email form
    if st.session_state.get("user_email"):
        return st.session_state.user_email

    st.markdown("## 🎣 Fishing Log")
    st.markdown("Enter your email to get started. Your data is private to you.")
    with st.form("login_form"):
        email = st.text_input("Email address")
        if st.form_submit_button("Sign in", type="primary"):
            if "@" in email and "." in email:
                st.session_state.user_email = email.lower().strip()
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
    st.stop()
    return ""  # unreachable


@st.cache_resource
def _bootstrap():
    """Wire up DATABASE_URL from secrets and initialise the engine once."""
    import os
    if "database_url" in st.secrets:
        os.environ["DATABASE_URL"] = st.secrets["database_url"]
    return True


def _refresh():
    """Clear cached data after a write so tables/map update."""
    st.cache_data.clear()


@st.cache_data
def _cached_sessions(date_from, date_to, location, species):
    return search.list_sessions(date_from, date_to, location, species)


@st.cache_data
def _cached_map_rows(date_from, date_to, location, species):
    return search.map_rows(date_from, date_to, location, species)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page_dashboard():
    st.header("🎣 Dashboard")
    stats = analytics.overall_stats()
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
    best = analytics.personal_bests()
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
    yoy = analytics.year_over_year()
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
    all_df = search.list_sessions()
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
        monthly = analytics.by_month(year)
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
        recent = search.list_sessions().head(5)
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
    view_zoom = st.session_state.get(zoom_key, 13)

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
            returned_objects=["last_clicked", "center", "zoom"],
            key=map_key,
        )
        if result:
            if result.get("zoom") is not None:
                st.session_state[zoom_key] = result["zoom"]
            ctr = result.get("center")
            if isinstance(ctr, dict) and ctr.get("lat") is not None:
                st.session_state[center_key] = (ctr["lat"], ctr["lng"])
            elif isinstance(ctr, (list, tuple)) and len(ctr) == 2:
                st.session_state[center_key] = (ctr[0], ctr[1])
            if result.get("last_clicked"):
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


def _photo_workbench(key_prefix: str):
    """Upload + EXIF-correct + rotate + crop one image. Returns the current
    cropped PIL image, or None if nothing is loaded. State is per key_prefix.

    The crop widget's key includes a version counter so it re-instantiates after
    each rotation — otherwise st_cropper keeps showing the original orientation.
    """
    img_key, ver_key, up_key = f"{key_prefix}_img", f"{key_prefix}_ver", f"{key_prefix}_upk"
    st.session_state.setdefault(img_key, None)
    st.session_state.setdefault(ver_key, 0)
    st.session_state.setdefault(up_key, 0)

    up = st.file_uploader(
        "Choose a photo",
        type=["jpg", "jpeg", "png", "gif", "bmp", "webp"],
        accept_multiple_files=False,
        key=f"{key_prefix}_up_{st.session_state[up_key]}",
    )
    if up is not None and st.session_state[img_key] is None:
        st.session_state[img_key] = media.load_image_oriented(up)  # honor EXIF
        st.session_state[ver_key] += 1

    if st.session_state[img_key] is None:
        return None

    rot1, rot2, _ = st.columns([1, 1, 4])
    if rot1.button("↺ Rotate left", key=f"{key_prefix}_rl"):
        st.session_state[img_key] = st.session_state[img_key].transpose(Image.Transpose.ROTATE_90)
        st.session_state[ver_key] += 1
        st.rerun()
    if rot2.button("↻ Rotate right", key=f"{key_prefix}_rr"):
        st.session_state[img_key] = st.session_state[img_key].transpose(Image.Transpose.ROTATE_270)
        st.session_state[ver_key] += 1
        st.rerun()

    st.caption("Drag the box to crop. The preview is exactly what will be saved.")
    edit_col, prev_col = st.columns([3, 2])
    with edit_col:
        cropped = st_cropper(
            st.session_state[img_key],
            realtime_update=True,
            box_color="#1f78b4",
            aspect_ratio=None,
            key=f"{key_prefix}_crop_{st.session_state[ver_key]}",
        )
    with prev_col:
        st.image(cropped, caption="Preview", width=220)
    return cropped


def _clear_workbench(key_prefix: str):
    st.session_state[f"{key_prefix}_img"] = None
    st.session_state[f"{key_prefix}_upk"] = st.session_state.get(f"{key_prefix}_upk", 0) + 1
    st.session_state[f"{key_prefix}_ver"] = st.session_state.get(f"{key_prefix}_ver", 0) + 1


def _photo_editor():
    """New-session photo staging: edited images accumulate in
    ``st.session_state.pending_photos`` and are saved when the form submits.
    """
    st.markdown("**📷 Photos** — upload, rotate/crop, then add to the trip (optional).")
    st.session_state.setdefault("pending_photos", [])

    cropped = _photo_workbench("new")
    if cropped is not None:
        add_col, discard_col, _ = st.columns([1, 1, 4])
        if add_col.button("➕ Add to trip", type="primary", key="new_add"):
            st.session_state.pending_photos.append(cropped.convert("RGB"))
            _clear_workbench("new")
            st.rerun()
        if discard_col.button("✖ Discard", key="new_discard"):
            _clear_workbench("new")
            st.rerun()

    pending = st.session_state.pending_photos
    if pending:
        st.write(f"**{len(pending)} photo(s) ready for this trip:**")
        cols = st.columns(min(4, len(pending)))
        for i, p in enumerate(pending):
            with cols[i % len(cols)]:
                st.image(p, width=180)
                if st.button("Remove", key=f"rm_photo_{i}"):
                    pending.pop(i)
                    st.rerun()


def _session_photo_manager(session_id: int):
    """View/remove existing photos and add new ones to an EXISTING session
    (used in edit mode; saves immediately rather than staging)."""
    kp = f"edit{session_id}"
    photos = media.get_photos(session_id)
    if photos:
        st.caption("Current photos:")
        cols = st.columns(min(4, len(photos)))
        for i, ph in enumerate(photos):
            with cols[i % len(cols)]:
                if os.path.exists(ph["abs_path"]):
                    st.image(ph["abs_path"], width=160)
                if st.button("Remove", key=f"{kp}_rm_{ph['id']}"):
                    media.delete_photo(ph["id"])
                    _refresh()
                    st.rerun()

    st.markdown("**Add a photo**")
    cropped = _photo_workbench(kp)
    if cropped is not None:
        add_col, discard_col, _ = st.columns([1, 1, 4])
        if add_col.button("➕ Save photo", type="primary", key=f"{kp}_add"):
            media.save_pil_images(session_id, [cropped.convert("RGB")])
            _clear_workbench(kp)
            _refresh()
            st.rerun()
        if discard_col.button("✖ Discard", key=f"{kp}_discard"):
            _clear_workbench(kp)
            st.rerun()


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
        df, num_rows="dynamic", width="stretch",
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
            if btn_col.button("✅ Step 2 — Mark as filed", key=f"dwr_file_{sid}"):
                n = data_entry.set_dwr_filed(sid, True)
                if n > 0:
                    st.session_state.pop("pending_dwr_sid", None)
                    _refresh()
                    st.rerun()
                else:
                    st.error("Could not mark as filed — try the checkbox in Browse & Search.")


def page_log_session():
    st.header("➕ Log a Session")

    # DWR nudge for the session just saved — stays until dismissed or replaced.
    if "pending_dwr_sid" in st.session_state:
        _dwr_nudge(st.session_state["pending_dwr_sid"])

    # Spot picker and photo editor live OUTSIDE the form so their controls
    # can rerun interactively (map clicks, rotate/crop).
    _spots_picker("spots", "loc_picker")
    _photo_editor()

    # Smart defaults: pre-fill from the most recent session and known baits.
    defaults = search.recent_defaults()
    prev_baits = search.baits_by_frequency()
    last_bait = defaults.get("bait_lure")
    weather_idx = (
        data_entry.WEATHER_OPTIONS.index(defaults["weather"])
        if defaults.get("weather") in data_entry.WEATHER_OPTIONS
        else 0
    )
    style_default = defaults.get("fishing_style") or "Planer Boards"
    style_idx = (
        data_entry.FISHING_STYLES.index(style_default)
        if style_default in data_entry.FISHING_STYLES
        else 0
    )

    with st.form("session_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            d = st.date_input("Date", value=date.today())
            start_time = st.text_input("Start time (HH:MM)", value="06:00")
            end_time = st.text_input("End time (HH:MM)", value="11:00")
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
            air_temp = st.number_input(
                "Air temp (°)", value=float(defaults.get("air_temp") or 70.0)
            )
            water_temp = st.number_input(
                "Water temp (°)", value=float(defaults.get("water_temp") or 60.0)
            )

        # Bait + style: reuse a previous bait (defaults to last used) and/or type a new one.
        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            bait_options = ["— pick a previous bait —"] + prev_baits
            bait_index = (
                bait_options.index(last_bait) if last_bait in bait_options else 0
            )
            bait_choice = st.selectbox(
                "Bait / lure (previous)", bait_options, index=bait_index
            )
        with bcol2:
            new_bait = st.text_input("…or new bait / lure")
        with bcol3:
            fishing_style = st.selectbox(
                "Style of fishing", data_entry.FISHING_STYLES, index=style_idx
            )

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
        # A typed new bait wins; otherwise use the chosen previous one.
        bait_lure = new_bait.strip() or (
            bait_choice if bait_choice in prev_baits else ""
        )
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
            saved_photos = media.save_pil_images(
                new_id, st.session_state.get("pending_photos", [])
            )
            _refresh()
            total = len(fish)
            # Clear staged spots/photos for the next entry.
            _clear_spot_state("spots", "loc_picker")
            st.session_state.pending_photos = []
            st.session_state.uploader_key = st.session_state.get("uploader_key", 0) + 1
            st.session_state["pending_dwr_sid"] = new_id
            photo_note = f" ({len(saved_photos)} photo(s))" if saved_photos else ""
            st.success(
                f"Saved session #{new_id} — {total} fish, {len(spots)} spot(s) "
                f"at {location_name}{photo_note}."
            )
        except data_entry.ValidationError as exc:
            st.error(f"Could not save: {exc}")


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
    photos = media.get_photos(int(r.id))
    thumb = next((p["abs_path"] for p in photos if os.path.exists(p["abs_path"])), None)
    selected = st.session_state.get("browse_sel") == int(r.id)
    with st.container(border=True):
        cthumb, cinfo = st.columns([1, 2])
        if thumb:
            cthumb.image(thumb, width=110)
        else:
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
    df = _cached_sessions(*_filter_controls("browse"))
    if df.empty:
        st.info("No sessions match these filters.")
        return

    tab_trips, tab_gallery = st.tabs([f"Trips ({len(df)})", "Photo gallery"])

    with tab_trips:
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

    with tab_gallery:
        gallery = []
        for r in df.itertuples():
            for ph in media.get_photos(int(r.id)):
                if os.path.exists(ph["abs_path"]):
                    cap = ph.get("caption") or f"{r.date} · {int(r.total_fish)} fish"
                    gallery.append((ph["abs_path"], cap))
        if not gallery:
            st.caption("No photos yet — add some when logging a trip.")
        else:
            st.caption(f"{len(gallery)} photo(s) — hover and click ⛶ to enlarge.")
            st.image([p for p, _ in gallery], caption=[c for _, c in gallery], width=200)


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

        fcol.checkbox("✅ Filed to DWR", key=fk, on_change=_toggle_filed)

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

    session_photos = [ph for ph in media.get_photos(sid) if os.path.exists(ph["abs_path"])]
    if session_photos:
        st.markdown("**Photos** — hover a photo and click the ⛶ icon (top-right) to view full size.")
        caps = [ph.get("caption") or "" for ph in session_photos]
        st.image([ph["abs_path"] for ph in session_photos],
                 caption=caps if any(caps) else None, width=240)

    with st.expander("✏️ Edit this session"):
        skey = f"edit_spots_{sid}"
        if skey not in st.session_state:
            st.session_state[skey] = [
                {"lat": s["latitude"], "lon": s["longitude"], "caught": bool(s.get("caught"))}
                for s in detail.get("spots", [])
            ]
        _spots_picker(skey, f"edit_map_{sid}")
        _edit_form(detail)
        st.divider()
        st.markdown("**📷 Photos**")
        _session_photo_manager(sid)

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

    with st.form(f"edit_form_{sid}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            d = st.date_input(
                "Date", value=datetime.strptime(detail["date"], "%Y-%m-%d").date(),
                key=f"e_date_{sid}",
            )
            start_time = st.text_input(
                "Start time (HH:MM)", value=detail.get("start_time") or "", key=f"e_start_{sid}"
            )
            end_time = st.text_input(
                "End time (HH:MM)", value=detail.get("end_time") or "", key=f"e_end_{sid}"
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
            air_temp = st.number_input(
                "Air temp (°)",
                value=float(detail["air_temp"]) if detail.get("air_temp") is not None else 70.0,
                key=f"e_air_{sid}",
            )
            water_temp = st.number_input(
                "Water temp (°)",
                value=float(detail["water_temp"]) if detail.get("water_temp") is not None else 60.0,
                key=f"e_water_{sid}",
            )

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            bait_lure = st.text_input(
                "Bait / lure", value=detail.get("bait_lure") or "", key=f"e_bait_{sid}"
            )
        with bcol2:
            fishing_style = st.selectbox(
                "Style of fishing", data_entry.FISHING_STYLES,
                index=_idx(data_entry.FISHING_STYLES, detail.get("fishing_style")),
                key=f"e_style_{sid}",
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
            "bait_lure": bait_lure, "fishing_style": fishing_style,
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
            width="stretch", hide_index=True,
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
            st.dataframe(tbl, width="stretch", hide_index=True)

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
            st.dataframe(sizes, width="stretch", hide_index=True)
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
                width="stretch", hide_index=True,
            )


def page_map():
    st.header("🗺️ Map")
    st.caption("Each spot is a dropped pin, color-coded by that trip's catch success: "
               "Skunked (0), Good (1–3), Great (4–6), Blowout (7+).")

    col_a, col_b = st.columns([3, 1])
    with col_b:
        fullscreen = st.checkbox("⛶ Full-screen map", value=False)

    filters = _filter_controls("map")
    df = _cached_map_rows(*filters)
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

    if st.button("💾 Export standalone map.html"):
        out = map_view.save_map(df, db.PROJECT_ROOT / "map.html")
        st.success(f"Saved to {out}")


def page_backup():
    st.header("💾 Backup & Export")

    st.subheader("Export to CSV (for Excel)")
    sessions_df = search.list_sessions()
    fish_df = search.fish_export()
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇ Sessions CSV", sessions_df.to_csv(index=False).encode("utf-8"),
        file_name="fishing_sessions.csv", mime="text/csv",
        disabled=sessions_df.empty,
    )
    c2.download_button(
        "⬇ Fish CSV (one row per fish)", fish_df.to_csv(index=False).encode("utf-8"),
        file_name="fishing_fish.csv", mime="text/csv",
        disabled=fish_df.empty,
    )

    st.divider()
    st.subheader("Backups")
    st.caption("A backup is made automatically each time the app starts "
               "(the 10 most recent are kept). You can also restore one here.")
    backups = backup.list_backups()
    if not backups:
        st.info("No backups yet.")
        return
    labels = {p.name: p for p in backups}
    chosen = st.selectbox("Available backups (newest first)", list(labels.keys()))
    st.caption("Restoring replaces your current data with the selected backup. "
               "Your current data is itself backed up first, just in case.")
    confirm = st.checkbox("Yes, restore this backup")
    if st.button("♻ Restore selected backup", type="primary", disabled=not confirm):
        backup.restore_backup(labels[chosen])
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success(f"Restored from {chosen}. Reloading…")
        st.rerun()


# --------------------------------------------------------------------------
# Sidebar / routing
# --------------------------------------------------------------------------

def main():
    _bootstrap()
    user_email = _get_user_email()   # shows login screen if not signed in
    db.set_current_user(user_email)  # all DB calls in this run are scoped to this user
    _inject_css()

    st.sidebar.title("🎣 Fishing Log")
    st.sidebar.caption(f"Signed in as **{user_email}**")
    if st.sidebar.button("Sign out"):
        st.session_state.pop("user_email", None)
        st.rerun()

    page = st.sidebar.radio(
        "Navigate",
        ["Dashboard", "Log a Session", "Browse & Search", "Analytics", "Map",
         "Export"],
    )

    _hero_banner()

    st.sidebar.divider()
    n_sessions = db.session_count()
    if n_sessions == 0:
        st.sidebar.info("No sessions yet — add one under **Log a Session**.")
    else:
        st.sidebar.caption(f"{n_sessions} sessions logged.")
        with st.sidebar.expander("⚠️ Clear my data"):
            st.caption("Deletes ALL your sessions and fish records. Cannot be undone.")
            confirm = st.checkbox("Yes, I'm sure")
            if st.button("Delete all my data", type="primary", disabled=not confirm):
                db.delete_all_sessions()
                _refresh()
                st.success("All your data deleted.")
                st.rerun()

    {
        "Dashboard": page_dashboard,
        "Log a Session": page_log_session,
        "Browse & Search": page_browse,
        "Analytics": page_analytics,
        "Map": page_map,
        "Export": page_backup,
    }[page]()


if __name__ == "__main__":
    main()
