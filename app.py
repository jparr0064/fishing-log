"""Fishing Log — Streamlit app entry point.

Run with:  streamlit run app.py

A thin presentation layer over the ``fishing_log`` package: every page
delegates data work to database / data_entry / search / analytics / map_view.
"""
from __future__ import annotations

import calendar as _cal
import html as _html
import logging
import os
from datetime import date, datetime

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from fishing_log import (
    analytics, auth_policy, backup_io, data_entry, database as db, dwr_report,
    map_view, observability as obs, search,
)

# Optional GPS button component; app still works if it isn't installed.
try:
    from streamlit_geolocation import streamlit_geolocation
except ImportError:  # pragma: no cover
    streamlit_geolocation = None

st.set_page_config(page_title="Fishing Log", page_icon="🎣", layout="wide")

# Shown at the bottom of the sidebar so we can tell at a glance which build
# the cloud is actually serving. Bump on each deploy-relevant change.
APP_BUILD = "2026-09-01.2"

# Default home water — pre-fills the Log a Session form.
DEFAULT_LOCATION = "Smith Mountain Lake"
DEFAULT_LAT = 37.16463
DEFAULT_LON = -79.70913

# The only species this log tracks.
SPECIES = ["Striper", "Largemouth Bass", "Smallmouth Bass", "Catfish", "Muskie"]

# Default "From" date for Map and Browse filters — start of year so all trips show.
DEFAULT_FROM_DATE = date(2026, 1, 1)

# Trip cards drawn per Browse page. Two per row, so this is 10 rows — enough to
# scan a season without building 500 card blocks on every rerun (CR-5).
BROWSE_PAGE_SIZE = 20

# Okabe-Ito color-blind-safe palette (distinguishable across CVD types).
CB_PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442"]


# Markdown metacharacters. Backslash-escaping is invisible in the rendered
# output (CommonMark drops the backslash), so this changes nothing a user sees
# except that their text is no longer interpreted.
_MD_SPECIAL = "\\`*_{}[]()#+-.!|>~"


def _plain(value) -> str:
    """User-authored text, made safe for a Markdown renderer (CR-9).

    st.markdown / st.write / st.info all parse Markdown, so a location name of
    `**Secret Spot**` renders bold and a trip note of `[free lures](http://…)`
    becomes a live link in someone else's browser. None of these fields are
    meant to be formatted — they are things an angler typed about a fish.

    The backslash must be escaped first, or it would double-escape the
    backslashes this function itself adds.
    """
    if value is None:
        return ""
    out = str(value)
    for ch in _MD_SPECIAL:
        out = out.replace(ch, "\\" + ch)
    return out


def _owner_health_panel():
    """Sidebar health readout, owner only (CR-10).

    Community Cloud has no metrics backend to ship to, so "monitoring" here is
    a panel the owner can read and a log line the owner can grep. The point is
    that repeated failures surface here rather than arriving as a phone call
    from a club member.
    """
    failures = obs.recent_failures()

    if obs.should_alert_owner():
        st.sidebar.error(
            f"⚠️ {len(failures)} failures in the last "
            f"{obs.ALERT_WINDOW_SECONDS // 60} min — check the logs.",
            icon="🚨",
        )

    label = f"📈 Health ({len(failures)} recent failures)" if failures else "📈 Health"
    with st.sidebar.expander(label):
        pool = obs.pool_stats(db.get_engine())
        if pool:
            st.caption(
                f"DB pool — {pool['checked_out']} in use, "
                f"capacity {pool['capacity']} "
                f"(base {pool['size']}, {pool['overflow']} overflow open)"
            )
            if pool.get("exhausted"):
                st.error("Connection pool exhausted.", icon="🔌")
        else:
            st.caption("DB pool — counters unavailable.")

        if not failures:
            st.caption("No failures recorded in this window.")
        else:
            for seconds_ago, event in reversed(failures[-8:]):
                st.caption(f"• {event} — {seconds_ago}s ago")
            if st.button("Clear", key="clear_failures"):
                obs.reset_failures()
                st.rerun()

        st.caption(f"Build {APP_BUILD}. Full tracebacks are in the server log; "
                   "search for the reference shown in the error.")


def _chart_ready(df, *value_cols) -> bool:
    """Whether a frame can actually be plotted (CR-9).

    Vega logs "infinite extent for field" warnings and draws an empty axis when
    handed an empty frame or a column that is all-NaN, which is how the browser
    console filled with them during normal demo use. Callers show a plain-text
    explanation instead.
    """
    if df is None or len(df) == 0:
        return False
    for col in value_cols:
        if col not in df.columns:
            return False
        series = pd.to_numeric(df[col], errors="coerce")
        if not series.notna().any():
            return False
    return True


def _chart_data_table(df, caption: str = "Show the numbers behind this chart"):
    """A text alternative for a chart (CR-9).

    A chart is an image to a screen reader and invisible to someone who cannot
    distinguish its colours. The same numbers in a table are readable by both,
    and by anyone who just wants the exact value. Collapsed so it does not
    crowd the visual layout.
    """
    with st.expander(caption):
        st.dataframe(df, width="stretch", hide_index=True)


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

          /* ---- Phone-only adjustments (desktop is untouched) ---- */
          @media (max-width: 640px) {
            /* enough top padding that the fixed "Menu" pill clears the hero banner */
            .block-container { padding-top: 4.6rem; padding-left: .8rem; padding-right: .8rem; }
            /* 44px minimum touch targets for buttons and inputs */
            .stButton button, .stDownloadButton button, .stLinkButton a {
              min-height: 44px; font-size: 1rem; padding: 10px 14px;
            }
            .stSelectbox [data-baseweb="select"], .stTextInput input,
            .stNumberInput input, .stDateInput input {
              min-height: 44px; font-size: 1rem;
            }
            [data-testid="stCheckbox"] { min-height: 40px; }
            /* Hero: stack title above the stat chips, spread chips full width */
            .hero { flex-direction: column; align-items: flex-start;
                    padding: 14px 16px; gap: 12px; }
            .hero-stats { width: 100%; justify-content: space-between; }
            .hero-chip { flex: 1; padding: 8px 6px; min-width: 0; }
            .hero-title { font-size: 1.3rem; }
            .hero-loc { font-size: 1rem; }
            /* Calendar nav: month title on its own top row, then all four
               buttons (incl. Year ago) sharing one even row beneath it */
            .st-key-cal_nav [data-testid="stHorizontalBlock"] {
              flex-wrap: wrap !important; gap: .3rem; align-items: center;
            }
            .st-key-cal_nav [data-testid="stColumn"],
            .st-key-cal_nav [data-testid="column"] {
              min-width: 0 !important; width: auto !important; flex: 1 1 auto !important;
            }
            .st-key-cal_nav [data-testid="stColumn"]:nth-child(3),
            .st-key-cal_nav [data-testid="column"]:nth-child(3) {
              order: -1; flex: 0 0 100% !important;   /* title first, full width */
            }
            .st-key-cal_nav .stButton button {
              min-height: 38px; padding: 6px 4px; font-size: .82rem;
              white-space: nowrap; width: 100%;
            }
            .st-key-cal_nav h3 { font-size: 1.1rem !important; padding-top: 0 !important; }
            /* Collapsed-sidebar control: the BUTTON itself is the "Menu" pill,
               so the whole pill (arrow + text) is one tap target */
            [data-testid="stSidebarCollapsedControl"] {
              background: transparent; padding: 0; box-shadow: none;
            }
            [data-testid="stSidebarCollapsedControl"] button {
              background: #0e7490 !important; color: #fff !important;
              border-radius: 10px; padding: 4px 14px 4px 6px;
              width: auto; min-height: 40px;
              display: inline-flex; align-items: center;
              box-shadow: 0 1px 4px rgba(0,0,0,.25);
            }
            [data-testid="stSidebarCollapsedControl"] button::after {
              content: "Menu"; color: #fff; font-weight: 600; font-size: .9rem;
              margin-left: 2px;
            }
            /* Open-sidebar collapse arrow: label it so it's obvious */
            [data-testid="stSidebarCollapseButton"] button::after {
              content: "Hide menu"; font-size: .85rem; font-weight: 600;
              margin-left: 4px;
            }
          }
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


def _fmt_temp(value) -> str:
    """Format a temperature with no trailing .0 — 82.0 -> '82'. Blank if missing.

    Temperatures come back from pandas as floats, so a plain f-string printed
    "82.0°" for a whole number and "nan°" for a missing one.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    if f != f:  # NaN (NaN != NaN)
        return ""
    return str(int(f)) if f == int(f) else str(f)


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


_auth_log = logging.getLogger("fishing_log.auth")


def _log_auth_problem(message: str) -> None:
    """Record an auth configuration failure.

    Only ever passed strings this module composed itself — never a secret value
    and never a raw exception message, which can carry connection strings or
    tokens. Exception paths log the type name only.
    """
    _auth_log.error("[auth] %s", message)


def _secret(name: str, default=""):
    """Read a secret, tolerating a missing or unreadable secrets.toml."""
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def _oidc_configured() -> bool:
    """True when an [auth] block is present in secrets.

    Deliberately a *configuration* check rather than a runtime probe. The
    previous version called st.user.is_logged_in inside a try/except and read
    any exception as "no OIDC", which silently downgraded production to the
    typed-email form. Configuration is a fact we can read; a probe is not.
    """
    try:
        auth = st.secrets.get("auth", None)
    except Exception:
        return False
    if not auth:
        return False
    try:
        return bool(dict(auth))
    except Exception:
        return True


def _auth_config() -> dict:
    """Auth configuration: secrets first, environment variable as fallback.

    Streamlit Cloud supplies settings through secrets; a container host is more
    likely to use env vars. Support both rather than forcing one.
    """
    return {
        "app_env": _secret("app_env", os.environ.get("APP_ENV", "")),
        "auth_mode": _secret("auth_mode", os.environ.get("AUTH_MODE", "")),
        "oidc_configured": _oidc_configured(),
    }


def _oidc_active() -> bool:
    """True when this deployment requires Google sign-in."""
    return auth_policy.resolve_auth(**_auth_config())[0] == auth_policy.AUTH_OIDC


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
    return auth_policy.allowed_emails(
        _secret("allowed_emails", []), _secret("dev_user_email", "")
    )


def _is_allowed(email: str) -> bool:
    """Whether this signed-in email may have a real account (approval list)."""
    return auth_policy.is_allowed(
        email, _secret("allowed_emails", []), _secret("dev_user_email", "")
    )


def _show_auth_unavailable_page() -> None:
    """Production auth is unusable — admit nobody, and reveal nothing.

    Reached when OIDC is required but unconfigured, or when the identity
    lookup itself fails. Deliberately offers no way in: no email form, and no
    detail a visitor could use to infer the misconfiguration.
    """
    st.markdown("## 🎣 Fishing Log")
    st.error(
        "**Sign-in is temporarily unavailable.**\n\n"
        "The app can't verify accounts right now, so it isn't letting anyone "
        "in. This is a configuration problem on our end, not something you "
        "did — please try again later.",
        icon="🔒",
    )
    st.caption("Owner: check the server log for `[auth]` entries.")


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
    """Return the current user's email, or stop to show a login/error screen.

    Configuration decides the route; ``auth_policy`` decides the outcome. The
    typed-email form appears only when the deployment declares itself
    development *and* selects local auth — never as a fallback from a failure.
    """
    # Demo shortcut — a fixed read-only account, set only by the demo button.
    # Never a user-supplied identity, so it bypasses auth in every mode.
    if st.session_state.get("user_email") == DEMO_EMAIL:
        return DEMO_EMAIL

    cfg = _auth_config()
    mode, _ = auth_policy.resolve_auth(**cfg)

    is_logged_in, email = False, ""
    if mode == auth_policy.AUTH_OIDC:
        try:
            user = _st_user()
            is_logged_in = bool(user.is_logged_in)
            email = (user.email or "") if is_logged_in else ""
        except Exception as exc:
            # The identity lookup itself failed. Fail closed: this is exactly
            # the case that used to drop through to the typed-email form.
            _log_auth_problem(f"OIDC identity lookup failed ({type(exc).__name__})")
            _show_auth_unavailable_page()
            st.stop()
            return ""  # unreachable
    elif mode == auth_policy.AUTH_LOCAL:
        email = st.session_state.get("user_email") or ""
        is_logged_in = bool(email)

    result = auth_policy.resolve_identity(
        **cfg,
        is_logged_in=is_logged_in,
        email=email,
        allowed_raw=_secret("allowed_emails", []),
        owner_email=_secret("dev_user_email", ""),
    )
    if result.reason:
        _log_auth_problem(result.reason)

    if result.outcome == auth_policy.OUTCOME_ALLOWED:
        return result.email

    if result.outcome == auth_policy.OUTCOME_NOT_APPROVED:
        _show_not_approved_page(result.email)
    elif result.outcome == auth_policy.OUTCOME_LOGIN_REQUIRED:
        _show_login_page(oidc=result.mode == auth_policy.AUTH_OIDC)
    else:
        _show_auth_unavailable_page()
    st.stop()
    return ""  # unreachable


DEMO_EMAIL = "demo@fishinglog.demo"


def _is_demo() -> bool:
    return db.get_current_user() == DEMO_EMAIL and not st.session_state.get("demo_admin_toggle")


# Columns the app expects beyond the original schema. Checked at startup,
# never created — see _bootstrap. Each maps to a file in migrations/.
_REQUIRED_COLUMNS = {
    ("spots", "fish_count"): "002_spots_fish_count.sql",
}


@st.cache_resource
def _bootstrap():
    """Wire up DATABASE_URL from secrets and verify the schema once.

    This used to run `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on every start.
    That stops working under CR-2: the runtime role is deliberately stripped of
    DDL rights, so a startup migration would fail on every boot — and a running
    app quietly altering its own schema is what "controlled migrations" (CR-4)
    exists to prevent. Schema changes now live in migrations/ and are applied
    deliberately with the fishing_deploy role.

    Startup only *checks*. Returns an error string naming the missing migration
    (surfaced to the owner in the sidebar), else None — never silently swallowed.
    """
    import os
    obs.configure_logging()
    if "database_url" in st.secrets:
        os.environ["DATABASE_URL"] = st.secrets["database_url"]
    try:
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.get_engine())
        missing = []
        for (table, column), migration in _REQUIRED_COLUMNS.items():
            names = {c["name"] for c in inspector.get_columns(table)}
            if column not in names:
                missing.append(f"{table}.{column} (run migrations/{migration})")
        if missing:
            msg = "Schema is behind: missing " + "; ".join(missing)
            _auth_log.error("[bootstrap] %s", msg)
            return msg
    except Exception as exc:
        # A failed *check* must not take the app down — but say so plainly.
        msg = f"Could not verify database schema ({type(exc).__name__})"
        _auth_log.error("[bootstrap] %s", msg)
        return msg
    return None


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
def _cached_last_spot(user_email, cache_ver=0):
    return search.last_spot()


@st.cache_data(ttl=300)
def _cached_locations(user_email, cache_ver=0):
    return search.distinct_locations()


@st.cache_data
def _user_guide_bytes():
    """The bundled user-guide PDF, or None if it isn't in the deploy."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "Fishing_Log_User_Guide.pdf")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


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
        if _chart_ready(monthly, "total_fish"):
            st.caption(f"Season {year}")
            st.altair_chart(
                alt.Chart(monthly).mark_bar(color=CB_PALETTE[0]).encode(
                    x=alt.X("month:N", sort=analytics.MONTH_ORDER, title=None),
                    y=alt.Y("total_fish:Q", title="Fish"),
                    tooltip=["month", "total_fish", "sessions"],
                ).properties(height=260, width="container")
            )
            _chart_data_table(monthly[["month", "sessions", "total_fish"]],
                              "Fish per month — the numbers")
        else:
            st.caption("No monthly totals to chart yet.")

    with right:
        st.subheader("Recent trips")
        recent = _cached_sessions(user, None, None, None, None, cache_ver=ver).head(5)
        if recent.empty:
            st.caption("No trips yet.")
        for r in recent.itertuples():
            big = _fmt_len(getattr(r, "biggest_length", None))
            big_txt = f" · biggest {big}" if big else ""
            with st.container(border=True):
                st.markdown(f"**{r.date}** · {_plain(r.location_name)}")
                st.markdown(
                    f"<span class='trip-meta'>{int(r.total_fish)} fish{big_txt}<br>"
                    f"{_html.escape(r.species_list) if r.species_list else 'skunked'}</span>",
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


def _spot_count_default(sp: dict) -> int:
    """Seed a spot's count input: stored count, else 1 for a legacy
    caught-only spot (recorded before counts existed), else 0."""
    if sp.get("fish_count") is not None:
        return int(sp["fish_count"])
    return 1 if sp.get("caught") else 0


def _sync_spot_counts(spots: list, map_key: str):
    """Mirror per-spot count widget state onto the spot dicts."""
    for i, sp in enumerate(spots):
        ck = f"{map_key}_c{i}"
        if ck not in st.session_state:
            st.session_state[ck] = _spot_count_default(sp)
        count = int(st.session_state[ck] or 0)
        sp["fish_count"] = count
        sp["caught"] = count > 0


def _spots_picker(state_key: str, map_key: str, defer_rerun: bool = False):
    """Multi-spot map picker (outside any form). Manages a list of
    {lat, lon, caught, fish_count} in ``st.session_state[state_key]``. Click
    the map to add each spot; enter how many fish you caught at each spot."""
    st.session_state.setdefault(state_key, [])
    spots = st.session_state[state_key]

    # Sync each spot's count/caught from widget state BEFORE drawing the map.
    _sync_spot_counts(spots, map_key)

    zoom_key, center_key = f"{map_key}_zoom", f"{map_key}_center"
    if spots:
        default_center = (spots[0]["lat"], spots[0]["lon"])
    else:
        # Center on the user's most recent trip's spot — most anglers return
        # to the same water. Falls back to the lake default for new users.
        default_center = _cached_last_spot(
            db.get_current_user(), cache_ver=_cache_ver()
        ) or (DEFAULT_LAT, DEFAULT_LON)
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
                # See _fish_editor: never st.rerun() while a form submit is
                # pending this run, or the save is silently lost.
                if not defer_rerun:
                    st.toast(f"📍 Spot {len(spots)} dropped — click again to add another.")
                    st.rerun()

    # Per-spot fish counts (0 = no fish there). Spots with fish show a 🐟 on
    # the map, with a ×N badge when 2 or more were caught at the same spot.
    if spots:
        st.caption("How many fish did you catch at each spot? "
                   "(0 = none — spots with fish show as a 🐟 on the map)")
        cols = st.columns(min(4, len(spots)))
        for i, sp in enumerate(spots):
            cols[i % len(cols)].number_input(
                f"Spot {i + 1} 🎣", min_value=0, step=1, key=f"{map_key}_c{i}",
            )
        _sync_spot_counts(spots, map_key)
        assigned = sum(sp.get("fish_count") or 0 for sp in spots)
        if assigned:
            st.caption(f"🐟 **{assigned} fish** assigned across "
                       f"{sum(1 for sp in spots if sp.get('fish_count'))} spot(s). "
                       "It doesn't have to match the fish table exactly — best guess is fine.")


# Most people logging here are striper fishing, so a row starts on Striper.
# It is set as the data_editor column DEFAULT, which applies only to rows the
# angler adds — never to a seeded row. That distinction matters: if an untouched
# table already contained a Striper, saving a skunked trip would silently log a
# fish that was never caught.
DEFAULT_SPECIES = "Striper"


def _blank_fish_df(rows: int = 1) -> pd.DataFrame:
    # dtypes are declared explicitly because an EMPTY frame has no values to
    # infer them from: pandas defaults every column to float64, and
    # st.data_editor then refuses a checkbox on a float ("column type
    # `checkbox` ... is not compatible with `float`").
    return pd.DataFrame({
        "species": pd.Series([DEFAULT_SPECIES] * rows, dtype="object"),
        "length": pd.Series([0.0] * rows, dtype="float64"),
        "depth": pd.Series([None] * rows, dtype="float64"),
        "weight": pd.Series([0.0] * rows, dtype="float64"),
        "kept": pd.Series([False] * rows, dtype="bool"),
        # Per-fish method. Blank means "caught the way the trip was", which is
        # what a single-technique day leaves them as — no extra clicks.
        "bait_lure": pd.Series([None] * rows, dtype="object"),
        "fishing_style": pd.Series([None] * rows, dtype="object"),
    })


_EDITOR_ROW_PX = 35  # glide-data-grid default row height in st.data_editor


def _reset_fish_editor(key: str):
    """Forget a fish editor's staged rows (call after a successful save)."""
    for k in (f"{key}_data", f"{key}_seed"):
        st.session_state.pop(k, None)
    ver = st.session_state.pop(f"{key}_ver", 0)
    st.session_state.pop(f"{key}_v{ver}", None)
    # The group inputs belong to the same catch — leaving them behind would
    # silently re-add this trip's groups to the next one.
    _reset_bulk_groups(key)


# Shown in the per-fish Bait/Style dropdowns to clear a row back to the trip's
# method. A real option rather than an empty string: Streamlit renders "None"
# for a blank cell, which reads like missing data instead of a deliberate
# "same as the trip".
SAME_AS_TRIP = "— same as trip —"


def _fish_editor(df: pd.DataFrame, key: str, defer_rerun: bool = False,
                 trip_bait: str | None = None, trip_style: str | None = None,
                 extra_baits: list | None = None, extra_styles: list | None = None):
    """A data editor with one row per fish: species, length, depth, weight, kept.

    Must be rendered OUTSIDE any st.form — inside a form the browser holds all
    edits until submit, so nothing server-side can react while the user types.
    Outside a form, every committed edit reruns the script, which lets us:

    - size the editor to fit EVERY row plus the trailing blank "add a fish"
      row, so the add-row never scrolls out of sight (no internal scrollbar,
      no false "you've maxed out" wall at ~10 rows), and
    - show a live "Fish entered: N" count below the table.

    Growing works by re-seeding under a VERSIONED widget key: the working
    frame lives in session state; when the row count changes we adopt the
    edited frame, bump the version (which gives the editor a brand-new key),
    and rerun so the height is recomputed. The new key is the load-bearing
    part: Streamlit keeps a keyed editor's added_rows/edited_rows deltas in
    session state and re-applies them when the same key re-mounts — so
    adopting added rows into the base WITHOUT changing the key makes the
    stale deltas append the same rows again on every rerun (rows multiply).
    A fresh key per adoption means the widget always starts clean on top of
    a base frame that already carries every committed value.
    """
    if "kept" not in df.columns:
        df = df.assign(kept=False)
    if "depth" not in df.columns:
        df = df.assign(depth=None)
    for _method_col, _trip_value in (("bait_lure", trip_bait),
                                     ("fishing_style", trip_style)):
        if _method_col not in df.columns:
            df = df.assign(**{_method_col: None})
        # Show the trip's method on every row rather than a blank. Blank was
        # recorded correctly (it means "same as the trip") but read as missing
        # data, so the angler could not see what a fish was being credited to.
        if _trip_value:
            df[_method_col] = df[_method_col].fillna(_trip_value)
    df["kept"] = df["kept"].fillna(False).astype(bool)

    data_key, seed_key, ver_key = f"{key}_data", f"{key}_seed", f"{key}_ver"
    st.session_state.setdefault(ver_key, 0)
    seed_fp = df.to_json(orient="records")
    if st.session_state.get(seed_key) != seed_fp:
        # Genuinely new seed (first render, or reopening after a save):
        # restart from it under a fresh widget key.
        st.session_state[seed_key] = seed_fp
        st.session_state[data_key] = df.reset_index(drop=True)
        st.session_state[ver_key] += 1
    base = st.session_state[data_key]
    # A new row inherits the method you last chose, falling back to the trip's.
    # Set spoons on the first fish and the rest follow, so a run of them costs
    # one click rather than one per fish. Copied, not written back to session
    # state: this is a display default, and persisting it would turn a value
    # the angler never touched into an explicit override.
    base = base.copy()
    for _col, _trip_value in (("bait_lure", trip_bait), ("fishing_style", trip_style)):
        if _col not in base.columns:
            continue
        _filled = base[_col].dropna()
        _last = _filled.iloc[-1] if not _filled.empty else None
        _default = _last if _last not in (None, "") else _trip_value
        if _default:
            base[_col] = base[_col].fillna(_default)
    widget_key = f"{key}_v{st.session_state[ver_key]}"

    # Header + every data row + the blank add-row, plus a small pad so
    # rounding never produces an internal scrollbar.
    height = (len(base) + 2) * _EDITOR_ROW_PX + 8

    edited = st.data_editor(
        base, num_rows="dynamic", use_container_width=True, height=height,
        column_config={
            "species": st.column_config.SelectboxColumn(
                "Species ▾", options=SPECIES, required=False,
                default=DEFAULT_SPECIES),
            "length": st.column_config.NumberColumn("Length (in)", min_value=0.0, step=0.5, format="%.1f"),
            "depth": st.column_config.NumberColumn("Depth (ft)", min_value=0.0, step=1.0, format="%.0f",
                                                    help="Depth at which this fish was caught (optional)"),
            "weight": st.column_config.NumberColumn("Weight (lb)", min_value=0.0, step=0.1, format="%.2f"),
            "kept": st.column_config.CheckboxColumn("Kept?", help="Checked = harvested/kept; unchecked = released", default=False),
            "bait_lure": st.column_config.SelectboxColumn(
                "Bait ▾",
                options=[SAME_AS_TRIP] + [b for b in dict.fromkeys(
                    list(data_entry.BAIT_LURE_OPTIONS) + list(search.baits_by_frequency())
                    + list(extra_baits or []) + ([trip_bait] if trip_bait else []))],
                required=False,
                help="Defaults to the trip's bait. Change it for a fish that came on "
                     f"something else, or pick \"{SAME_AS_TRIP}\" to clear it."),
            "fishing_style": st.column_config.SelectboxColumn(
                "Style ▾",
                options=[SAME_AS_TRIP] + [s_ for s_ in dict.fromkeys(
                    list(data_entry.FISHING_STYLES) + list(search.styles_by_frequency())
                    + list(extra_styles or []) + ([trip_style] if trip_style else []))],
                required=False,
                help="Defaults to the trip's style. Change it for a fish caught a "
                     f"different way, or pick \"{SAME_AS_TRIP}\" to clear it."),
        },
        column_order=["species", "length", "depth", "weight", "kept",
                      "bait_lure", "fishing_style"],
        key=widget_key,
    )

    if len(edited) != len(base):
        # Rows were added or deleted — adopt the edited frame (it carries all
        # committed values), retire this widget's deltas, and remount under a
        # new key with a height that fits the new row count.
        st.session_state[data_key] = edited.reset_index(drop=True)
        st.session_state[ver_key] += 1
        st.session_state.pop(widget_key, None)
        # defer_rerun=True means a form submit is pending THIS run. st.rerun()
        # here would abort the script before the submit is processed — the
        # click (and the save) would be silently lost while every widget kept
        # its old value, which looks like "the app kept my previous session".
        # The adoption above is already complete, so just let the run continue;
        # the remount (and correct height) happens on the next natural rerun.
        if not defer_rerun:
            st.rerun()

    n = len(_fish_from_editor(edited))
    if n:
        extra = " (blank rows aren't counted)" if len(edited) > n else ""
        st.caption(f"🎣 **Fish entered: {n}**{extra}")
    else:
        st.caption("🎣 **Fish entered: 0** — leave the table blank for a skunked trip.")
    return edited


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
        def _method(col):
            v = r.get(col)
            if pd.isna(v):
                return None
            v = str(v).strip()
            # The sentinel means "same as the trip", which is stored as NULL.
            return None if not v or v == SAME_AS_TRIP else v
        out.append({"species": sp, "length": length, "weight": weight, "kept": kept,
                    "depth": depth,
                    "bait_lure": _method("bait_lure"),
                    "fishing_style": _method("fishing_style")})
    return out



def _extra_methods(key: str) -> tuple:
    """Per-fish baits/styles the angler typed in that aren't in the pick-lists.

    Kept separate from the trip section's "Add new bait" box on purpose. That
    box defines the trip's PRIMARY method, so using it to introduce a technique
    you only tried on four fish would relabel the whole outing. These stay
    local to the catch table and are offered as options there.

    Only for the current run of the app: once a fish is saved with one, it
    shows up in the pick-lists on its own, because _methods_by_frequency reads
    fish rows as well as sessions.
    """
    bait_key, style_key = f"{key}_xbait", f"{key}_xstyle"
    baits = st.session_state.setdefault(bait_key, [])
    styles = st.session_state.setdefault(style_key, [])

    with st.expander("➕ Add a bait or style that isn't in the list"):
        st.caption(
            "For something you're using today. Once you log it — as your primary "
            "method or on any fish — it stays in your list for future trips."
        )
        c1, c2, c3 = st.columns([3, 3, 1.4])
        nb = c1.text_input("New bait / lure", key=f"{bait_key}_in")
        ns = c2.text_input("New fishing style", key=f"{style_key}_in")
        c3.write("")
        if c3.button("Add", key=f"{key}_xadd"):
            if nb.strip() and nb.strip() not in baits:
                baits.append(nb.strip())
            if ns.strip() and ns.strip() not in styles:
                styles.append(ns.strip())
        if baits or styles:
            st.caption("Available on this trip: "
                       + ", ".join(baits + styles))
    return baits, styles


def _bulk_key(key: str) -> str:
    return f"{key}_bulk"


def _bulk_fish_section(key: str, trip_bait: str | None = None,
                       trip_style: str | None = None,
                       extra_baits: list | None = None,
                       extra_styles: list | None = None) -> list:
    """Fish that were counted but not measured — plain inputs, not a table.

    This has been through three shapes. First a set of inputs plus an "Add
    group" button: that lost a user's whole catch, because on a phone the
    button sat below the fold and was never pressed. Then a data_editor to
    match the fish table above: that dropped the first value typed into a
    cell.

    The likely reason for the second failure is worth recording. A
    data_editor's edits live inside the widget, and Streamlit discards a
    widget's contents on any run where the widget is not drawn. The fish table
    and the map above this one both call st.rerun() while adjusting
    themselves, and a rerun aborts the script before this section renders — so
    a value typed just before one of those refreshes was thrown away. The fish
    table survives the same treatment because it keeps its rows in
    st.session_state as well, not only in the widget.

    Plain widgets sidestep all of it: each one owns its value under its own
    key. They also read better on a phone than a seven-column table that has
    to scroll sideways.
    """
    n_key = f"{key}_ngroups"
    n = st.session_state.setdefault(n_key, 1)

    bait_opts = list(dict.fromkeys(
        list(data_entry.BAIT_LURE_OPTIONS) + list(search.baits_by_frequency())
        + list(extra_baits or []) + ([trip_bait] if trip_bait else [])))
    style_opts = list(dict.fromkeys(
        list(data_entry.FISHING_STYLES) + list(search.styles_by_frequency())
        + list(extra_styles or []) + ([trip_style] if trip_style else [])))
    # No "same as trip" sentinel here: nobody could tell what it meant. The
    # dropdowns simply start on the trip's primary method, which is the same
    # thing said plainly. Picking that value still stores NULL underneath, so
    # the fish keeps following the trip rather than pinning a copy of it.
    bait_choices = bait_opts or [""]
    style_choices = style_opts or [""]
    bait_idx = bait_choices.index(trip_bait) if trip_bait in bait_choices else 0
    style_idx = style_choices.index(trip_style) if trip_style in style_choices else 0

    groups = []
    for i in range(n):
        with st.container(border=True):
            c1, c2 = st.columns([2, 1])
            species = c1.selectbox(
                "Species", SPECIES,
                index=SPECIES.index(DEFAULT_SPECIES) if DEFAULT_SPECIES in SPECIES else 0,
                key=f"{key}_g{i}_sp")
            # value=None leaves the box EMPTY so a typed number replaces
            # nothing. Starting at 0.0 meant typing 22 produced 0.0022 unless
            # you first selected the zero — which is not how the fish table
            # above behaves.
            count = c2.number_input(
                "How many", min_value=1, max_value=int(data_entry.MAX_BULK_COUNT),
                value=None, step=1, placeholder="e.g. 17", key=f"{key}_g{i}_n")

            c3, c4, c5 = st.columns([1, 1, 1])
            lo = c3.number_input("Smallest (in)", min_value=0.0, step=0.5,
                                 value=None, format="%.1f", placeholder="optional",
                                 key=f"{key}_g{i}_lo")
            hi = c4.number_input("Largest (in)", min_value=0.0, step=0.5,
                                 value=None, format="%.1f", placeholder="optional",
                                 key=f"{key}_g{i}_hi")
            kept = c5.checkbox("Kept?", key=f"{key}_g{i}_kept")

            c6, c7 = st.columns(2)
            bait = c6.selectbox("Bait", bait_choices, index=bait_idx,
                                key=f"{key}_g{i}_bait")
            style = c7.selectbox("Style", style_choices, index=style_idx,
                                 key=f"{key}_g{i}_style")

        if count and int(count) > 0:
            groups.append({
                "species": species, "count": int(count),
                "len_min": lo or None, "len_max": hi or None,
                "kept": bool(kept),
                # Matching the trip's method is stored as NULL — "caught the
                # way the trip was" — so editing the trip later still flows
                # through to these fish.
                "bait_lure": None if bait == trip_bait else bait,
                "fishing_style": None if style == trip_style else style,
            })

    st.caption("Add another group for fish caught a different way, or a "
               "different species or size range.")
    if st.button("➕  Add another group", key=f"{key}_addgroup"):
        st.session_state[n_key] = n + 1
        st.rerun()

    return groups


def _reset_bulk_groups(key: str) -> None:
    """Clear the group inputs after a save."""
    for k in [k for k in list(st.session_state) if k.startswith(f"{key}_g")]:
        st.session_state.pop(k, None)
    st.session_state.pop(f"{key}_ngroups", None)


def _dwr_size_preview(fish_items: list):
    """Show the exact DWR sizes text when this catch will report a range.

    Rendered live while the catch is being entered, from the same
    dwr_report.range_notice() the DWR card uses later, so the angler is never
    told one thing here and shown another on the form. Stripers only — DWR's
    journal covers nothing else.
    """
    try:
        fish = data_entry.validate_fish(fish_items)
    except data_entry.ValidationError:
        return                      # mid-edit; the save path reports the error
    notice = dwr_report.range_notice({"fish": fish})
    if not notice:
        return
    harvested_sizes, released_sizes, _n = notice
    st.info(
        "**This is what the DWR form will show for sizes:**\n\n"
        f"- Harvested: `{harvested_sizes}`\n"
        f"- Released: `{released_sizes}`\n\n"
        "Add individual lengths if you don't want the range displayed on the DWR form."
    )


def _dwr_nudge(sid: int):
    """DWR filing card shown at the top of Log a Session after saving."""
    detail = search.get_session(sid)
    if not detail:
        return
    report = dwr_report.summarize(detail)
    already_filed = bool(detail.get("dwr_filed"))
    n_stripers = report["harvested_n"] + report["released_n"]
    total_fish = int(detail.get("total_fish") or 0)

    with st.container(border=True):
        hcol, xcol = st.columns([11, 1])
        hcol.markdown(
            f"**📋 DWR Striper Report — {detail['date']} · {detail['location_name']}**  \n"
            f"Stripers caught: **{n_stripers}** "
            f"({report['harvested_n']} kept · {report['released_n']} released) · "
            f"Anglers: **{report['anglers']}** · "
            f"Hours: **{report['hours'] or '—'}**"
        )
        if xcol.button("✕", key=f"dwr_nx_{sid}", help="Dismiss"):
            st.session_state.pop("pending_dwr_sid", None)
            st.rerun()

        # Safety nets: make a bad save impossible to miss, and explain why the
        # numbers can legitimately be zero.
        if total_fish == 0:
            st.warning(
                "This session saved with **0 fish**. If you did catch fish and "
                "they're missing here, they didn't make it into the save — add "
                "them under **Browse & Search → Edit this session** before "
                "filing the report.",
                icon="⚠️",
            )
        elif n_stripers == 0:
            st.caption("ℹ️ This trip's fish were all non-striper species — the DWR "
                       "journal only counts stripers, so the report shows zeros.")

        if already_filed:
            filed_on = detail.get("dwr_filed_at")
            st.success("✅ Filed to DWR"
                       + (f" on {filed_on}" if filed_on else "")
                       + " — you're done with this trip. Dismiss this card with ✕, "
                         "or just log your next session.")
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
                try:
                    n = data_entry.set_dwr_filed(_sid, new_val)
                except data_entry.SaveError as exc:
                    st.session_state.pop(_key, None)  # revert display to DB value
                    st.toast(f"⚠️ {exc}", icon="⚠️")
                    return
                if n == 0:
                    st.session_state.pop(_key, None)
                    st.toast("⚠️ Could not save — try again.", icon="⚠️")
                elif new_val:
                    # Keep the card on screen: it re-renders in its ✅ "Filed —
                    # you're done" state so it's obvious the trip is complete
                    # (vanishing silently made people wonder what happened).
                    st.toast("✅ Marked as filed to DWR — you're done with this trip.")
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

    # ------------------------------------------------------------------
    # Layout vs execution order.
    #
    # These containers fix WHERE things appear; the code below fixes WHEN they
    # run, and the two are deliberately different. The Save button is drawn
    # last (people expect Save at the bottom) but READ first, so that by the
    # time the map and the catch tables execute we already know a save is
    # pending and can stop them calling st.rerun() mid-save. A rerun issued
    # before the save is processed silently discards it — nothing saves,
    # nothing clears, and the page looks stuck on the previous trip. That was
    # the July lost-save bug.
    #
    # st.form used to provide this ordering, but a form cannot contain the map
    # or the catch tables (nothing inside a form can react while you use it),
    # which is exactly why saving used to be split across the page. A plain
    # button has no such restriction, so one Save can now commit everything.
    # ------------------------------------------------------------------
    # A trip that has just been saved is finished. Showing the form again —
    # filled in, editable, with a live Save button — invites someone to
    # "correct" a trip that is already in the database and save a duplicate.
    # So a save replaces the page with its outcome.
    if msg := st.session_state.get("log_saved_msg"):
        st.success("✅  Trip saved.")
        st.info(msg)
        if "pending_dwr_sid" in st.session_state:
            _dwr_nudge(st.session_state["pending_dwr_sid"])
        st.divider()
        if st.button("➕  Log another trip", type="primary",
                     use_container_width=True, key="log_another"):
            st.session_state.pop("log_saved_msg", None)
            st.session_state.pop("pending_dwr_sid", None)
            st.rerun()
        st.caption("To change the trip you just saved, open it under "
                   "**Browse & Search** and edit it there.")
        return

    sec_trip = st.container()
    sec_where = st.container()
    sec_catch = st.container()
    save_slot = st.container()

    with save_slot:
        st.divider()
        save = st.button("💾  Save this trip", type="primary",
                         use_container_width=True, key="log_save")
        st.caption("Saves everything above — the trip, the map, and every fish. "
                   "If you logged stripers, a DWR report option appears next.")

    # Smart defaults: pre-fill from the most recent session and known baits.
    defaults = search.recent_defaults()
    weather_idx = (
        data_entry.WEATHER_OPTIONS.index(defaults["weather"])
        if defaults.get("weather") in data_entry.WEATHER_OPTIONS
        else 0
    )

    # ---------------- 1. The trip -------------------------------------
    with sec_trip:
        st.subheader("1 · The trip")
        fields_box = st.container()
        method_box = st.container()
        extras_box = st.container()

    # Executes before the method dropdowns so a bait added here is selectable
    # immediately, but draws below them.
    with extras_box:
        x_baits, x_styles = _extra_methods("catch_editor")

    with fields_box:
        c1, c2 = st.columns(2)
        with c1:
            d = st.date_input("Date", value=date.today(), key="log_date")
            location_name = st.text_input("Location", value=DEFAULT_LOCATION,
                                          key="log_loc")
        with c2:
            start_time = _time_picker("Start time", "06:00", "log_start")
            end_time = _time_picker("End time", "11:00", "log_end")
        c3, c4 = st.columns(2)
        with c3:
            weather = st.selectbox("Weather", data_entry.WEATHER_OPTIONS,
                                   index=weather_idx, key="log_weather")
        with c4:
            num_anglers = st.number_input(
                "Anglers", min_value=1, value=1, step=1, key="log_anglers",
                help="Used for the DWR striper report.")

        with st.expander("More detail (optional)"):
            t1, t2 = st.columns(2)
            # Blank by default — don't invent a reading nobody took.
            air_temp = t1.number_input("Air temp (°)", value=None, step=1,
                                       format="%d", placeholder="optional",
                                       key="log_air")
            water_temp = t2.number_input("Water temp (°)", value=None, step=1,
                                         format="%d", placeholder="optional",
                                         key="log_water")
            notes = st.text_area("Notes", height=80, key="log_notes")

    with method_box:
        # ONE bait and ONE style, deliberately: this is the trip's primary
        # method. It is what the fish rows default to, and on a skunked trip it
        # is the only record of how the day was fished. It is also the
        # denominator for success-rate-by-method, which two primaries would
        # break. Anything else tried goes on the individual fish below.
        st.markdown("**Primary fishing method used this day**")
        all_baits = list(dict.fromkeys(
            list(data_entry.BAIT_LURE_OPTIONS) + list(search.baits_by_frequency())
            + list(x_baits)))
        all_styles = list(dict.fromkeys(
            list(data_entry.FISHING_STYLES) + list(search.styles_by_frequency())
            + list(x_styles)))
        last_bait = defaults.get("bait_lure")
        style_default = defaults.get("fishing_style") or "Downlines"
        m1, m2 = st.columns(2)
        bait_choice = m1.selectbox(
            "Bait / lure", all_baits,
            index=all_baits.index(last_bait) if last_bait in all_baits else 0,
            key="log_bait")
        fishing_style = m2.selectbox(
            "Style of fishing", all_styles,
            index=all_styles.index(style_default) if style_default in all_styles else 0,
            key="log_style")
        st.caption("Any other techniques used today can be added individually "
                   "as you log each fish.")

    trip_bait = bait_choice or None
    trip_style = fishing_style or None

    # ---------------- 2. Where you fished ------------------------------
    with sec_where:
        st.subheader("2 · Where you fished")
        st.caption("Drop a pin for each spot, or skip it — a trip saves fine without one.")
        _spots_picker("spots", "loc_picker", defer_rerun=save)

    # ---------------- 3. What you caught -------------------------------
    with sec_catch:
        st.subheader("3 · What you caught")

        # The disambiguator for a seeded row. Both tables start with a row
        # already set to Striper, which is one less click on a normal trip —
        # but it also means an untouched table is no longer proof that nothing
        # was caught. This checkbox says so explicitly, and it makes a skunked
        # trip a deliberate act rather than a side effect of leaving things
        # blank.
        skunked = st.checkbox(
            "🚫  No fish caught (skunked trip)", key="log_skunked",
            help="Tick this and the tables below are ignored — a blank trip is "
                 "still worth logging, and it feeds your success-rate stats.")

        if skunked:
            st.caption("The catch tables are being ignored. Press Save to log this "
                       "as a skunked trip.")

        st.markdown("**Fish you measured** — one row each")
        catch_editor = _fish_editor(_blank_fish_df(), key="catch_editor",
                                    defer_rerun=save,
                                    trip_bait=trip_bait, trip_style=trip_style,
                                    extra_baits=x_baits, extra_styles=x_styles)

        st.markdown("**Fish you counted but didn't measure**")
        st.caption("How many, and the size range you saw. Recorded as a range — "
                   "never turned into individual lengths.")
        bulk_groups = _bulk_fish_section("catch_editor",
                                         trip_bait=trip_bait, trip_style=trip_style,
                                         extra_baits=x_baits, extra_styles=x_styles)

        # One count covering both tables. The fish table prints its own
        # "Fish entered: N" and the groups printed nothing, so a 22-fish group
        # looked like it had not registered at all.
        _measured = len(_fish_from_editor(catch_editor))
        _grouped = sum(int(g["count"]) for g in bulk_groups)
        if skunked:
            st.info("**Skunked trip** — the tables above are being ignored.")
        elif _measured or _grouped:
            st.success(
                f"**{_measured + _grouped} fish this trip** — "
                f"{_measured} measured individually, {_grouped} in groups."
            )
        else:
            st.caption("No fish entered yet. Save as-is to log a skunked trip, "
                       "or tick the box above to be explicit about it.")

        _dwr_size_preview(_fish_from_editor(catch_editor) + bulk_groups)

    # ---------------- save ---------------------------------------------
    if save:
        # A skunked trip records no fish no matter what the tables hold.
        fish = [] if skunked else (_fish_from_editor(catch_editor) + bulk_groups)
        # No coordinate fallback: a trip with no pin saves with no coordinates
        # rather than inventing one at the lake default, which fabricated a
        # location and distorted the Map page.
        spots = list(st.session_state.get("spots", []))
        session = {
            "date": d, "start_time": start_time, "end_time": end_time,
            "location_name": location_name, "weather": weather,
            "air_temp": air_temp, "water_temp": water_temp,
            "bait_lure": bait_choice, "fishing_style": fishing_style,
            "num_anglers": num_anglers, "notes": notes,
        }
        try:
            # The page takes a few seconds to save, most of it spent redrawing
            # the map. Without this the screen just greys out and comes back,
            # which reads as "nothing happened" and invites a second click.
            with st.spinner("Saving your trip…"):
                new_id = data_entry.add_session(session, fish, spots)
            _refresh()
            _clear_spot_state("spots", "loc_picker")
            st.session_state["pending_dwr_sid"] = new_id
            n = len(fish)
            if n:
                species_counts = {}
                for f_ in fish:
                    species_counts[f_["species"]] = species_counts.get(f_["species"], 0) + 1
                breakdown = ", ".join(f"{v} × {k}" for k, v in sorted(species_counts.items()))
                st.session_state["log_saved_msg"] = (
                    f"✅ Trip saved — **{n} fish** ({breakdown}), "
                    f"{len(spots)} spot(s) at {location_name}. "
                    "Check that matches what you entered."
                )
            else:
                st.session_state["log_saved_msg"] = (
                    f"✅ Skunked trip saved at {location_name}. Still worth logging."
                )
            _reset_fish_editor("catch_editor")
            _reset_bulk_groups("catch_editor")
            _reset_entry_fields("log_")
            st.rerun()
        except data_entry.ValidationError as exc:
            st.error(f"Could not save: {exc}")
        except data_entry.SaveError as exc:
            # Rolled back — nothing was written, so retrying is safe and cannot
            # duplicate the trip. Entered values are deliberately left in place
            # so nobody has to retype a whole outing.
            st.error(str(exc), icon="⚠️")


# Keys that share the entry-field prefix but must SURVIVE a save. Without this
# the cleanup below deleted the very message that puts the page into its
# "saved" state, so the Save button never changed and it looked like nothing
# had happened.
_KEEP_AFTER_SAVE = {"log_saved_msg"}


def _reset_entry_fields(prefix: str) -> None:
    """Clear the entry widgets after a save.

    st.form's clear_on_submit used to do this. Without a form the widget values
    live in session_state under their keys, so they are dropped by hand; the
    rerun that follows recreates them at their defaults.
    """
    for k in [k for k in list(st.session_state)
              if k.startswith(prefix) and k not in _KEEP_AFTER_SAVE]:
        st.session_state.pop(k, None)


def _filter_controls(key_prefix: str):
    """Shared date/location/species filter widgets. Returns the filter values.

    Locations come from the user's actual data (was hardcoded to the lake
    name, which matched nothing when trips used names like "SML — …")."""
    locations = [""] + _cached_locations(db.get_current_user(), _cache_ver())
    species_opts = [""] + SPECIES
    c1, c2, c3, c4 = st.columns(4)
    # Distinct, self-describing labels (CR-9). "From" and "To" alone give a
    # screen reader two near-identical date fields with no clue what they
    # bound; read aloud out of visual context they are indistinguishable.
    with c1:
        date_from = st.date_input(
            "Show trips from", value=DEFAULT_FROM_DATE, key=f"{key_prefix}_from",
            help="Earliest trip date to include.",
        )
    with c2:
        date_to = st.date_input(
            "Show trips until", value=date.today(), key=f"{key_prefix}_to",
            help="Latest trip date to include.",
        )
    with c3:
        location = st.selectbox("Filter by location", locations, key=f"{key_prefix}_loc")
    with c4:
        species = st.selectbox("Filter by species", species_opts, key=f"{key_prefix}_sp")
    return (
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
        location or None,
        species or None,
    )


def _trip_card(r):
    """A compact, clickable trip summary card for the Browse grid."""
    with st.container(border=True):
        cthumb, cinfo = st.columns([1, 2])
        cthumb.markdown("<div style='font-size:40px;text-align:center'>🎣</div>",
                        unsafe_allow_html=True)
        big = _fmt_len(getattr(r, "biggest_length", None))
        big_txt = f" · biggest {big}" if big else ""
        # pd.isna, not `in (None, "")`: a missing number arrives from pandas as
        # NaN, which is neither of those, so the old check let it through and
        # the card read "water nan°".
        water = getattr(r, "water_temp", None)
        cond = (getattr(r, "weather", "") or "")
        if water is not None and water != "" and not pd.isna(water):
            cond += f" · water {_fmt_temp(water)}°"
        cinfo.markdown(f"**{r.date}** · {r.location_name}")
        cinfo.markdown(
            f"<span class='trip-meta'>{int(r.total_fish)} fish{big_txt}<br>"
            f"{_html.escape(r.species_list) if r.species_list else 'skunked'}<br>"
            f"{_html.escape(cond)}</span>",
            unsafe_allow_html=True,
        )
        if cinfo.button("Open trip →", key=f"view_{int(r.id)}",
                        use_container_width=True):
            st.session_state["browse_sel"] = int(r.id)
            st.rerun()


def page_browse():
    """Two views: a list of trips, or ONE trip on its own.

    Previously both were on screen at once — the detail redrew below a grid of
    cards, so choosing a trip appeared to do nothing unless you knew to scroll
    past every card to find it. Selecting something should take you to it.
    """
    if msg := st.session_state.pop("saved_msg", None):
        st.success(msg)

    sel = st.session_state.get("browse_sel")
    if sel:
        detail = search.get_session(int(sel))
        if detail:
            _browse_detail_view(detail, int(sel))
            return
        # The trip is gone (deleted, or a stale id) — fall back to the list.
        st.session_state.pop("browse_sel", None)

    _browse_list_view()


def _browse_list_view():
    st.header("🔍 Browse & Search")

    # Filters are for finding one trip among many; most visits are "show me
    # what I did lately", which the default order already answers. Collapsed
    # unless they are actually in use, so they stop occupying the top of the
    # page on a phone.
    active = any(st.session_state.get(f"browse_{k}") for k in ("loc", "sp"))
    with st.expander("🔎 Filter trips", expanded=active):
        filters = _filter_controls("browse")

    df = _cached_sessions(db.get_current_user(), *filters, cache_ver=_cache_ver())
    if df.empty:
        st.info("No trips match these filters.")
        return

    all_rows = list(df.itertuples())

    # Paginate: a 500-trip account rendered every card on every run, and each
    # card is a column block with its own markdown (CR-5). The filters above
    # remain the way to search across everything — this only bounds how much
    # is drawn at once.
    total_pages = max(1, -(-len(all_rows) // BROWSE_PAGE_SIZE))  # ceil
    page = 1
    if total_pages > 1:
        page = st.number_input(
            f"Page (showing {BROWSE_PAGE_SIZE} of {len(all_rows)} trips)",
            min_value=1, max_value=total_pages, value=1, step=1,
            key="browse_page",
        )
    start = (int(page) - 1) * BROWSE_PAGE_SIZE
    sessions = all_rows[start:start + BROWSE_PAGE_SIZE]

    st.caption(f"{len(all_rows)} trip(s) · newest first. Tap a trip to open it.")

    for i in range(0, len(sessions), 2):  # 2 cards per row
        cols = st.columns(2)
        for j, r in enumerate(sessions[i:i + 2]):
            with cols[j]:
                _trip_card(r)

    if total_pages > 1:
        st.caption(f"Page {int(page)} of {total_pages} · {len(all_rows)} trips match "
                   "these filters. Narrow the filters above to find a specific trip.")


def _browse_detail_view(detail: dict, sid: int):
    """One trip, on its own, with a way back."""
    if st.button("←  Back to all trips", key="browse_back"):
        st.session_state.pop("browse_sel", None)
        st.rerun()

    st.header(f"{detail['date']} · {_plain(detail['location_name'])}")
    _render_session_detail(detail, sid)

    st.divider()
    if st.button("←  Back to all trips", key="browse_back_bottom"):
        st.session_state.pop("browse_sel", None)
        st.rerun()


def _render_session_detail(detail: dict, sid: int):
    """One trip: either read it, or edit it — never both at once.

    Editing used to open an expander that pushed a full entry form ABOVE the
    read-only summary, so the same trip appeared twice on one screen, once
    editable and once not. Now editing swaps the view, the same way opening a
    trip swaps away from the list.
    """
    detail_spots = detail.get("spots") or []
    edit_key = f"editing_{sid}"

    if st.session_state.get(edit_key) and not _is_demo():
        if st.button("←  Cancel editing", key=f"cancel_edit_{sid}"):
            st.session_state.pop(edit_key, None)
            _clear_spot_state(f"edit_spots_{sid}", f"edit_map_{sid}")
            _reset_fish_editor(f"e_fish_{sid}")
            st.rerun()

        st.subheader("✏️ Editing this trip")
        if detail.get("dwr_filed"):
            filed_on = detail.get("dwr_filed_at")
            st.warning(
                "This trip's DWR striper report was already filed"
                + (f" on {filed_on}" if filed_on else "")
                + " — changes you save here won't update what the state received. "
                "If the catch details changed materially, contact DWR directly.",
                icon="📋",
            )
            if st.button("Marked as filed by mistake? Unmark", key=f"unfile_{sid}"):
                try:
                    data_entry.set_dwr_filed(sid, False)
                except data_entry.SaveError as exc:
                    st.error(str(exc), icon="⚠️")
                else:
                    st.session_state.pop(f"dwr_filed_{sid}", None)
                    _refresh()
                    st.rerun()

        skey = f"edit_spots_{sid}"
        if skey not in st.session_state:
            st.session_state[skey] = [
                {"lat": s["latitude"], "lon": s["longitude"],
                 "caught": bool(s.get("caught")),
                 "fish_count": s.get("fish_count")}
                for s in detail.get("spots", [])
            ]
        _edit_form(detail)
        return

    if not _is_demo():
        if st.button("✏️  Edit this trip", key=f"edit_{sid}",
                     use_container_width=True):
            st.session_state[edit_key] = True
            st.rerun()

    left, right = st.columns(2)
    with left:
        st.write(f"**Date:** {detail['date']}")
        st.write(f"**Location:** {_plain(detail['location_name'])}")
        st.write(f"**Time:** {detail.get('start_time')} – {detail.get('end_time')} "
                 f"({detail.get('hours_fished')} h)")
        st.write(f"**Spots:** {len(detail_spots)}"
                 + (f" · {sum(bool(s.get('caught')) for s in detail_spots)} with fish"
                    if detail_spots else ""))
    with right:
        st.write(f"**Weather:** {_plain(detail.get('weather'))}")
        # Show only the readings actually taken — printing "None°" or "nan°"
        # for a temperature nobody recorded reads as broken software.
        _air, _wat = _fmt_temp(detail.get("air_temp")), _fmt_temp(detail.get("water_temp"))
        if _air or _wat:
            st.write(f"**Air / Water:** {_air + '°' if _air else '—'} / "
                     f"{_wat + '°' if _wat else '—'}")
        st.write(f"**Bait/Lure:** {_plain(detail.get('bait_lure'))}")
        st.write(f"**Style:** {detail.get('fishing_style') or 'n/a'}")
        st.write(f"**Anglers:** {detail.get('num_anglers') or 1}")
        st.write(f"**Total fish:** {detail['total_fish']}")
        if detail.get("moon_phase"):
            st.write(f"**Moon:** {_plain(detail['moon_phase'])}")
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
        st.info(_plain(detail["notes"]))

    # DWR Striped Bass Angler Journal — pre-filled Google Form for this outing.
    report = dwr_report.summarize(detail)
    with st.container(border=True):
        st.markdown("**📋 DWR Striped Bass Angler Journal**")
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Stripers harvested", report["harvested_n"])
        rc2.metric("Stripers released", report["released_n"])
        rc3.metric("Anglers", report["anglers"])
        st.caption(f"Harvested sizes: {report['harvested_sizes'] or '—'}  •  "
                   f"Released sizes: {report['released_sizes'] or '—'}")

        if detail.get("dwr_filed"):
            # Filed = done deal. The report is the state's copy now; no re-filing
            # from here (a new trip means a new report on a new record).
            filed_on = detail.get("dwr_filed_at")
            st.success("DWR striper report filed"
                       + (f" on {filed_on}" if filed_on else "") + ".", icon="✅")
        else:
            st.caption("Pre-fills the official Google Form for this outing — just review "
                       "and hit Submit. The form collects your email from your Google login.")
            bcol, fcol = st.columns([2, 2])
            bcol.link_button("🎣 Step 1 — Open pre-filled DWR report",
                             dwr_report.prefilled_url(detail), type="primary")
            fk = f"dwr_filed_{sid}"
            if fk not in st.session_state:
                st.session_state[fk] = False

            def _toggle_filed(_sid=sid, _key=fk):
                try:
                    n = data_entry.set_dwr_filed(_sid, st.session_state[_key])
                except data_entry.SaveError as exc:
                    st.session_state.pop(_key, None)  # revert display to DB value
                    st.toast(f"⚠️ {exc}", icon="⚠️")
                    return
                if n == 0:
                    st.session_state.pop(_key, None)  # revert display to DB value
                    st.toast("⚠️ DWR status could not be saved — try again.", icon="⚠️")
                _refresh()

            fcol.checkbox("Step 2 — Mark as filed to DWR", key=fk, on_change=_toggle_filed,
                          disabled=_is_demo())

    if detail_spots:
        st.markdown(f"**🗺️ Trolling route** ({len(detail_spots)} spot(s)) — "
                    "numbered in order; the arrowed line shows direction; "
                    "🐟 marks where a fish was caught (×N = how many).")
        route_pts = [
            {"lat": s["latitude"], "lon": s["longitude"],
             "caught": bool(s.get("caught")), "fish_count": s.get("fish_count")}
            for s in detail_spots
        ]
        st_folium(map_view.build_route_map(route_pts), height=320,
                  use_container_width=True, returned_objects=[], key=f"route_{sid}")

    if not _is_demo():
        # Two-step delete: the first click only arms a confirmation row —
        # deleting a trip is irreversible, so it must never be one click.
        arm_key = f"del_arm_{sid}"
        if not st.session_state.get(arm_key):
            if st.button("🗑️ Delete this session", type="secondary", key=f"del_{sid}"):
                st.session_state[arm_key] = True
                st.rerun()
        else:
            st.warning(
                f"Delete the **{detail['date']}** trip at "
                f"**{detail['location_name']}**? This can't be undone — the trip, "
                "its fish, and its route are removed permanently.",
                icon="⚠️",
            )
            c_yes, c_no = st.columns([1, 1])
            if c_yes.button("Yes — delete permanently", type="primary", key=f"del_yes_{sid}"):
                try:
                    data_entry.delete_session(sid)
                except data_entry.SaveError as exc:
                    # Rolled back — the trip is still there. Leave the confirm
                    # armed so they can retry without re-arming it.
                    st.error(str(exc), icon="⚠️")
                    st.stop()
                _refresh()
                st.session_state.pop(arm_key, None)
                st.session_state.pop("browse_sel", None)
                st.success("Session deleted.")
                st.rerun()
            if c_no.button("Cancel", key=f"del_no_{sid}"):
                st.session_state.pop(arm_key, None)
                st.rerun()


def _edit_form(detail: dict):
    """Edit an existing trip.

    Deliberately the SAME three sections, in the same order, with the same
    single Save as page_log_session — entering a trip and correcting one are
    the same task, and having them mirror each other was actively confusing.

    Kept as its own function rather than shared code with page_log_session:
    the two differ in real ways (existing values, preserving dwr_filed, no
    skunked shortcut, a different message on save), and folding them together
    would mean a pile of mode flags through one long function. The section
    headings and order are what has to match, and they do.
    """
    sid = detail["id"]

    def _idx(options, value, default=0):
        return options.index(value) if value in options else default

    # Read Save FIRST, draw it LAST — same reason as page_log_session: the
    # catch tables and the map below must know a save is pending before they
    # can call st.rerun() and swallow it.
    sec_trip = st.container()
    sec_where = st.container()
    sec_catch = st.container()
    save_slot = st.container()

    with save_slot:
        st.divider()
        saved = st.button("💾  Save changes", type="primary",
                          use_container_width=True, key=f"e_save_{sid}")
        st.caption("Saves everything above — the trip, the map, and every fish.")

    edit_all_baits = list(dict.fromkeys(
        list(data_entry.BAIT_LURE_OPTIONS) + list(search.baits_by_frequency())))
    edit_all_styles = list(dict.fromkeys(
        list(data_entry.FISHING_STYLES) + list(search.styles_by_frequency())))
    existing_bait = detail.get("bait_lure") or ""
    existing_style = detail.get("fishing_style") or ""
    existing = (
        pd.DataFrame(detail["fish"]) if detail["fish"] else _blank_fish_df(1)
    )

    # ---------------- 1. The trip -------------------------------------
    with sec_trip:
        st.subheader("1 · The trip")
        fields_box = st.container()
        method_box = st.container()
        extras_box = st.container()

    with extras_box:
        x_baits_e, x_styles_e = _extra_methods(f"e_fish_{sid}")

    with fields_box:
        c1, c2 = st.columns(2)
        with c1:
            d = st.date_input(
                "Date", value=datetime.strptime(detail["date"], "%Y-%m-%d").date(),
                key=f"e_date_{sid}")
            location_name = st.text_input(
                "Location", value=detail.get("location_name") or DEFAULT_LOCATION,
                key=f"e_loc_{sid}")
        with c2:
            start_time = _time_picker(
                "Start time", detail.get("start_time") or "06:00", f"e_start_{sid}")
            end_time = _time_picker(
                "End time", detail.get("end_time") or "11:00", f"e_end_{sid}")
        c3, c4 = st.columns(2)
        with c3:
            weather = st.selectbox(
                "Weather", data_entry.WEATHER_OPTIONS,
                index=_idx(data_entry.WEATHER_OPTIONS, detail.get("weather")),
                key=f"e_weather_{sid}")
        with c4:
            num_anglers = st.number_input(
                "Anglers", min_value=1, step=1,
                value=int(detail.get("num_anglers") or 1), key=f"e_anglers_{sid}")

        with st.expander("More detail (optional)"):
            t1, t2 = st.columns(2)
            # Keep an existing reading; otherwise blank (don't invent 70/60).
            air_temp = t1.number_input(
                "Air temp (°)",
                value=int(float(detail["air_temp"])) if detail.get("air_temp") is not None else None,
                step=1, format="%d", key=f"e_air_{sid}", placeholder="optional")
            water_temp = t2.number_input(
                "Water temp (°)",
                value=int(float(detail["water_temp"])) if detail.get("water_temp") is not None else None,
                step=1, format="%d", key=f"e_water_{sid}", placeholder="optional")
            notes = st.text_area("Notes", value=detail.get("notes") or "",
                                 key=f"e_notes_{sid}")

    with method_box:
        st.markdown("**Primary fishing method used this day**")
        all_b = list(dict.fromkeys(edit_all_baits + list(x_baits_e)
                                   + ([existing_bait] if existing_bait else [])))
        all_s = list(dict.fromkeys(edit_all_styles + list(x_styles_e)
                                   + ([existing_style] if existing_style else [])))
        m1, m2 = st.columns(2)
        bait_choice_e = m1.selectbox("Bait / lure", all_b,
                                     index=_idx(all_b, existing_bait),
                                     key=f"e_bait_{sid}")
        fishing_style_e = m2.selectbox("Style of fishing", all_s,
                                       index=_idx(all_s, existing_style),
                                       key=f"e_style_{sid}")
        st.caption("Any other techniques used that day can be set on individual fish.")

    trip_bait_e = bait_choice_e or None
    trip_style_e = fishing_style_e or None

    # ---------------- 2. Where you fished ------------------------------
    with sec_where:
        st.subheader("2 · Where you fished")
        _spots_picker(f"edit_spots_{sid}", f"edit_map_{sid}", defer_rerun=saved)

    # ---------------- 3. What you caught -------------------------------
    with sec_catch:
        st.subheader("3 · What you caught")
        st.markdown("**Fish you measured** — one row each")
        catch_editor = _fish_editor(existing, key=f"e_fish_{sid}", defer_rerun=saved,
                                    trip_bait=trip_bait_e, trip_style=trip_style_e,
                                    extra_baits=x_baits_e, extra_styles=x_styles_e)

        st.markdown("**Fish you counted but didn't measure**")
        bulk_groups = _bulk_fish_section(f"e_fish_{sid}",
                                         trip_bait=trip_bait_e, trip_style=trip_style_e,
                                         extra_baits=x_baits_e, extra_styles=x_styles_e)

        _measured = len(_fish_from_editor(catch_editor))
        _grouped = sum(int(g["count"]) for g in bulk_groups)
        if _measured or _grouped:
            st.success(
                f"**{_measured + _grouped} fish this trip** — "
                f"{_measured} measured individually, {_grouped} in groups."
            )
        else:
            st.caption("No fish on this trip.")

        _dwr_size_preview(_fish_from_editor(catch_editor) + bulk_groups)

    if saved:
        fish = _fish_from_editor(catch_editor) + bulk_groups
        spots = list(st.session_state.get(f"edit_spots_{sid}", []))
        session = {
            "date": d, "start_time": start_time, "end_time": end_time,
            "location_name": location_name,
            "weather": weather, "air_temp": air_temp, "water_temp": water_temp,
            "bait_lure": bait_choice_e,
            "fishing_style": fishing_style_e,
            "num_anglers": num_anglers, "notes": notes,
            # Preserve filed status — without this, validate_session defaults it
            # to 0 and every edit would silently un-file the DWR report.
            "dwr_filed": detail.get("dwr_filed"),
        }
        try:
            with st.spinner("Saving your changes…"):
                data_entry.update_session(sid, session, fish, spots)
            _refresh()
            # Reset edit state so the expander collapses and reloads fresh.
            _clear_spot_state(f"edit_spots_{sid}", f"edit_map_{sid}")
            _reset_fish_editor(f"e_fish_{sid}")
            _reset_bulk_groups(f"e_fish_{sid}")
            st.session_state.pop(f"editing_{sid}", None)   # back to reading it
            st.session_state["saved_msg"] = f"✅ Trip #{sid} changes saved."
            st.rerun()
        except data_entry.ValidationError as exc:
            st.error(f"Could not save: {exc}")
        except data_entry.SaveError as exc:
            # Rolled back — the original trip, its fish and its spots are all
            # still intact. Retrying is safe.
            st.error(str(exc), icon="⚠️")


def _render_whats_working():
    """Condition insights: which water temp, weather, time, style, bait produce."""
    bests = analytics.best_conditions(min_sessions=2)
    if bests:
        st.markdown("**Your most productive conditions** — ranked by fish per hour "
                    "(only categories with 2+ trips qualify)")
        cols = st.columns(len(bests))
        for col, (dim, label, fph, n) in zip(cols, bests):
            col.metric(dim, label, f"{fph} fish/hr")
            col.caption(
                f"🌱 Early signal — {n} trips" if n < analytics.ESTABLISHED_SESSIONS
                else f"✅ Established — {n} trips"
            )
    else:
        st.caption("Not enough repeat data yet — a condition needs at least two "
                   "trips (with hours recorded) before it can rank here. Keep logging!")

    # Per-fish attribution. The tables below are per-TRIP: they credit every
    # fish on an outing to the one method recorded for it, which is wrong on
    # exactly the days two techniques were used at once. This section counts
    # each fish against the method that actually caught it.
    for _title, _dim in (("What actually caught them — by bait",  "bait_lure"),
                         ("What actually caught them — by style", "fishing_style")):
        _tbl = analytics.by_method(_dim)
        if _tbl is None or _tbl.empty:
            continue
        st.subheader(_title)
        _show = _tbl.rename(columns={
            _dim: _title.split("— by ")[-1].title(),
            "total_fish": "fish", "trips": "trips",
            "fish_per_hour": "fish/hr", "rate_trips": "rate from",
        })
        st.dataframe(_show, hide_index=True, width="stretch")
        st.caption(
            "**fish** counts every fish, credited to the method that caught it. "
            "**fish/hr** is calculated only from trips where you used that one "
            "method — on a trip running two techniques at once there is no way to "
            "know how the hours divided, so the rate is left out rather than "
            "guessed. **rate from** is how many trips fed that rate."
        )

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


def page_privacy():
    """Privacy & Data (CR-8).

    Written from what the code actually does, not from a template. Two details
    that a generic policy would miss and that matter here: exact coordinates
    are stored and exported, and there is no server-side backup — the ZIP the
    angler downloads is the only copy that can bring their trips back.

    Set a `privacy_contact` secret to publish a contact address; the owner's
    dev_user_email is deliberately NOT shown, since this page is public.
    """
    st.header("🔒 Privacy & Your Data")
    st.caption("What this app stores, who can see it, and what happens if you leave.")

    st.subheader("The short version")
    st.markdown(
        "- Your trips are **private to your account**. Other members cannot see them.\n"
        "- The app stores the **exact coordinates** of your fishing spots.\n"
        "- The person who runs this app **can see all data**, including yours.\n"
        "- **There is no server-side backup.** If your data is deleted, only a "
        "backup ZIP you downloaded yourself can bring it back."
    )

    st.subheader("Where your data lives")
    st.markdown(
        "- **Supabase** hosts the database holding every trip, fish, and map pin.\n"
        "- **Streamlit Community Cloud** runs the app itself.\n"
        "\n"
        "Both are third-party services with their own privacy terms. Neither is "
        "operated by the person running this fishing log."
    )

    st.subheader("What leaves your browser")
    st.markdown(
        "- **Map tiles** are fetched from **OpenStreetMap** whenever you open a "
        "map. Their servers can see the map area you are looking at.\n"
        "- **Signing in** goes through **Google**. The app receives your email "
        "address; it never sees your Google password.\n"
        "- **The \"use my location\" button** asks your device for its GPS "
        "position. Your browser will prompt first, and you can decline — you "
        "can always drop pins on the map by hand instead.\n"
        "- **Filing a DWR report** opens a **Google Form** run by the Virginia "
        "Department of Wildlife Resources, pre-filled with that trip's details. "
        "Nothing is submitted until you press Submit on their form. The app "
        "does not fill in your email — Google supplies it from the account you "
        "are signed into. What DWR does with a submitted report is governed by "
        "their policy, not this app's."
    )

    st.subheader("Fishing spots are stored exactly")
    st.markdown(
        "Every pin you drop is saved as a precise latitude and longitude, not a "
        "rounded or approximate area. That is what makes the route map and the "
        "catch heatmap work.\n\n"
        "Those exact coordinates are included in **every export and backup file** "
        "you download. If you share a backup ZIP or a CSV with someone, you are "
        "sharing your fishing spots with them. There is no setting to blur or "
        "round them."
    )

    st.subheader("Who can access your data")
    st.markdown(
        "- **You**, when signed in.\n"
        "- **The app owner**, who holds the database credentials and can "
        "therefore read, change, or delete any account's data. This is not a "
        "special feature — it is what running the database means.\n"
        "- **Supabase and Streamlit staff**, to the extent their own terms allow.\n"
        "\n"
        "Accounts are **approval-only**: signing in with Google is not enough, "
        "the owner has to add your address to the approved list first. Everyone "
        "else sees the read-only demo."
    )

    st.subheader("Keeping and deleting your data")
    st.markdown(
        "- Trips are kept **until you delete them**. Nothing expires or is "
        "removed automatically.\n"
        "- **Delete one trip** from Browse & Search — that removes its fish and "
        "route pins too.\n"
        "- **Delete everything** from the sidebar under *⚠️ Clear my data*. It "
        "makes you download a backup first, on purpose.\n"
        "- Deletion is **immediate and permanent**. There is no undo, no bin to "
        "recover from, and no snapshot to roll back to.\n"
        "- A DWR report you already submitted is **held by the state**, not by "
        "this app. Deleting the trip here does not withdraw it."
    )

    st.subheader("Backups are your responsibility")
    st.warning(
        "**No copy of your trips is kept anywhere you can reach.** If the "
        "database is lost, or you delete something by mistake, the only way "
        "back is a backup ZIP you downloaded yourself.\n\n"
        "Download one from **Export** every month or so and keep it somewhere "
        "safe.",
        icon="⚠️",
    )

    contact = _secret("privacy_contact", "")
    if contact:
        st.subheader("Questions")
        st.markdown(
            f"Ask the person who runs this app: **{contact}**. They can remove "
            "your account and its data on request."
        )
    else:
        st.subheader("Questions")
        st.caption(
            "Contact whoever set this app up for your club — they can remove "
            "your account and its data on request."
        )

    st.divider()
    st.caption(
        "This page describes how the app behaves. It is not a legal document, "
        "and it is not legal advice."
    )


def page_analytics():
    st.header("📊 Analytics")
    if analytics.overall_stats()["sessions"] == 0:
        st.info("No data yet.")
        return

    years = analytics.available_years()
    year = st.selectbox("Year", years, index=0) if years else None

    # A selector, not st.tabs. Streamlit computes every tab body on every run
    # even though three of the four are hidden, so the old layout built all
    # four sections — tables, charts and their queries — to show one (CR-5).
    # A radio also announces itself properly to a screen reader, which the tab
    # strip did not.
    section = st.radio(
        "Analytics section",
        ["Monthly", "Sizes", "Personal Bests", "What's working"],
        horizontal=True,
        key="analytics_section",
    )

    if section == "What's working":
        _render_whats_working()

    elif section == "Monthly":
        tbl = analytics.by_month(year)
        if tbl.empty:
            st.info("No data for this year.")
        else:
            # Altair fields can't contain '%', so use a chart-friendly copy.
            chart_df = tbl.rename(columns={"success_rate_%": "success_rate"})
            st.subheader(f"Monthly summary — {year}")
            st.dataframe(tbl, use_container_width=True, hide_index=True)

            st.subheader("Fish caught per month")
            if _chart_ready(chart_df, "total_fish"):
                st.altair_chart(
                    alt.Chart(chart_df).mark_bar(color="#1a9850").encode(
                        x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                        y=alt.Y("total_fish:Q", title="Fish caught"),
                        tooltip=["month", "total_fish", "sessions", "success_rate"],
                    ).properties(height=320, width="container")
                )
            else:
                st.caption("Nothing to chart for this year — the table above has "
                           "the full picture.")

            st.subheader("Success rate by month (%)")
            if _chart_ready(chart_df, "success_rate"):
                st.altair_chart(
                    alt.Chart(chart_df).mark_line(point=True, color="#2c7fb8").encode(
                        x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                        y=alt.Y("success_rate:Q", title="Success rate %",
                                scale=alt.Scale(domain=[0, 100])),
                        tooltip=["month", "success_rate", "sessions_with_fish", "sessions"],
                    ).properties(height=280, width="container")
                )
            else:
                st.caption("No success rates recorded for this year yet.")

    elif section == "Sizes":
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
            if _chart_ready(melted, "inches"):
                st.altair_chart(
                    alt.Chart(melted).mark_line(point=True).encode(
                        x=alt.X("month:N", sort=analytics.MONTH_ORDER, title="Month"),
                        y=alt.Y("inches:Q", title="Length (in)"),
                        color=alt.Color("metric:N", title="",
                                        scale=alt.Scale(range=CB_PALETTE[:2])),
                        tooltip=["month", "metric", "inches"],
                    ).properties(height=300, width="container")
                )
            else:
                st.caption("No measured lengths this year — the table above lists "
                           "what was recorded.")

            st.subheader("Length distribution (in)")
            fish = analytics.fish_sizes(year)
            fish = fish[fish["length"] > 0] if not fish.empty else fish
            if not _chart_ready(fish, "length"):
                st.caption("No measured lengths yet.")
            else:
                st.altair_chart(
                    alt.Chart(fish).mark_bar(color="#1f78b4").encode(
                        x=alt.X("length:Q", bin=alt.Bin(step=2), title="Length (in)"),
                        y=alt.Y("count()", title="Number of fish"),
                        tooltip=[alt.Tooltip("count()", title="fish")],
                    ).properties(height=300, width="container")
                )
                # Text alternative: the histogram is otherwise unreadable to a
                # screen reader and to anyone who cannot see the bar heights.
                buckets = (
                    fish.assign(band=(fish["length"] // 2 * 2).astype(int))
                        .groupby("band").size().reset_index(name="fish")
                )
                buckets["Length band (in)"] = buckets["band"].map(
                    lambda b: f"{b}–{b + 2}")
                _chart_data_table(buckets[["Length band (in)", "fish"]],
                                  "Length distribution — the numbers")

    elif section == "Personal Bests":
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
    st.header("💾 Backup & Export")

    n_sessions = db.session_count()

    # --- Full backup (the real thing) ---
    st.markdown(
        "**Full backup** — one ZIP with everything: `sessions.csv`, `fish.csv` "
        "(kept/released + record IDs), `spots.csv` (route order, coordinates, "
        "caught, fish counts), and a restorable `backup.json`."
    )
    if n_sessions:
        st.download_button(
            "⬇️ Download full backup (ZIP)",
            data=backup_io.build_zip_bytes(),
            file_name=f"fishing_log_backup_{date.today().isoformat()}.zip",
            mime="application/zip",
            type="primary",
        )
        st.caption("Grab one every month or so and keep it somewhere safe.")
        with st.expander("📱 On a phone? Where the file goes, and what to do next"):
            st.markdown(
                "The download lands in **Files → Downloads** on an iPhone, or your "
                "**Downloads** folder on Android.\n\n"
                "**Then move it off the phone.** A backup sitting only on the phone "
                "does not survive losing the phone — and there is no copy on our side "
                "to fall back on.\n\n"
                "- **iPhone:** Files → Downloads → press and hold the file → **Move** → "
                "iCloud Drive. Or Share → Mail it to yourself.\n"
                "- **Android:** Files → Downloads → **Share → Save to Drive**. Or email it.\n\n"
                "Emailing it to yourself is the simplest — it is off the phone, dated, "
                "and easy to search for later.\n\n"
                "**If the button seems to do nothing:** you are probably in an in-app "
                "browser (opened from Facebook, Messenger, and so on), which blocks "
                "downloads. Open the app in Safari or Chrome instead."
            )
    else:
        st.caption("No trips yet — nothing to back up.")

    # --- Spreadsheet-friendly singles ---
    with st.expander("Individual CSVs (for Excel / Google Sheets)"):
        sessions_df = search.list_sessions()
        fish_df = search.fish_export()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Sessions** — one row per trip")
            st.download_button(
                "⬇ Sessions CSV",
                # to_safe_csv, not to_csv: these open straight into Excel and
                # Google Sheets, so a note beginning '=' would be executed.
                backup_io.to_safe_csv(sessions_df).encode("utf-8"),
                file_name="fishing_sessions.csv", mime="text/csv",
                disabled=sessions_df.empty, use_container_width=True,
            )
        with c2:
            st.markdown("**Fish** — one row per fish caught")
            st.download_button(
                "⬇ Fish CSV",
                backup_io.to_safe_csv(fish_df).encode("utf-8"),
                file_name="fishing_fish.csv", mime="text/csv",
                disabled=fish_df.empty, use_container_width=True,
            )

    # --- Restore ---
    st.divider()
    st.markdown("**Restore from backup**")
    if _is_demo():
        st.caption("🔒 Restore is disabled in the demo.")
        return
    st.caption(
        "Upload a backup ZIP (or just its backup.json) to load those trips back "
        "into your account. You'll see exactly what will happen before anything "
        "is written."
    )
    up = st.file_uploader("Backup file", type=["zip", "json"], key="restore_file")
    skip_dupes = st.checkbox("Skip trips I already have (recommended)", value=True)

    if up is None:
        return

    # Parse and preview on every rerun. Nothing here touches the database's
    # contents — restore only happens when the button below is pressed, so the
    # angler decides with the real numbers in front of them (CR-7).
    try:
        data = backup_io.parse_backup(up.getvalue())
    except ValueError as exc:
        st.error(str(exc), icon="🚫")
        return

    plan = backup_io.preview_restore(data, skip_duplicates=skip_dupes)

    st.markdown("**Before you restore**")
    p1, p2, p3 = st.columns(3)
    p1.metric("Trips in file", plan["total"])
    p2.metric("Will be added", plan["to_restore"])
    p3.metric("Already have", plan["duplicates"])
    st.caption(
        f"Adds {plan['fish']} fish and {plan['spots']} route pin(s). "
        + (f"Duplicates matched by {plan['matched_by']}."
           if plan["duplicates"] else "No duplicates found.")
    )
    for msg in plan["warnings"]:
        st.warning(msg, icon="⚠️")

    if plan["to_restore"] == 0:
        st.info("Nothing to add — every trip in this file is already in your log.",
                icon="ℹ️")
        return

    if st.button(f"↩️ Restore {plan['to_restore']} trip(s)", type="primary"):
        result = backup_io.restore_backup(data, skip_duplicates=skip_dupes)
        _refresh()
        st.success(
            f"Restore complete — **{result['restored']} trip(s) restored**, "
            f"{result['skipped']} skipped as duplicates."
        )
        for msg in result["errors"]:
            st.warning(msg)


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

/* Phone-only: compress the grid so a full month fits without side-scrolling */
@media (max-width: 640px) {
  .fc-wrap{padding:8px;border-radius:10px;}
  .fc-table th{font-size:9px;padding:4px 1px;}
  .fc-table td{height:56px;padding:2px 3px;}
  .day-n{font-size:11px;}
  .day-n.today-n{width:18px;height:18px;line-height:18px;font-size:10px;}
  .moon-e{font-size:10px;}
  .trip-fish,.trip-sk{font-size:9px;margin-top:1px;}
  .trip-multi{font-size:8px;}
  .trip-loc{display:none;} /* location doesn't fit — shown in the trip list below */
  .fc-legend{gap:10px;font-size:10px;flex-wrap:wrap;}
}
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
                    rows += f'<div class="trip-loc">{_html.escape(s["location"])}</div>'
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

    # Navigation bar (keyed container so mobile CSS can keep it on one row)
    with st.container(key="cal_nav"):
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
    boot_err = _bootstrap()
    user_email = _get_user_email()   # shows login screen if not signed in
    db.set_current_user(user_email)  # all DB calls in this run are scoped to this user

    # Demo admin: let the dev account edit demo data directly via a sidebar toggle.
    dev_email = st.secrets.get("dev_user_email", "")
    if user_email == dev_email:
        if boot_err:
            st.sidebar.warning(f"⚠️ {boot_err}", icon="⚠️")
        demo_admin = st.sidebar.toggle("🛠 Edit demo data", key="demo_admin_toggle")
        if demo_admin:
            db.set_current_user(DEMO_EMAIL)
        _owner_health_panel()
        with st.sidebar.expander("🩺 DWR form health check"):
            st.caption("Fetches the DWR Google Form and verifies every hardcoded "
                       "entry ID still exists — run after any DWR form change.")
            if st.button("Run check", key="dwr_health_btn"):
                ok, missing = dwr_report.check_form_health()
                if ok:
                    st.success("All DWR form field IDs found — prefill is healthy.")
                else:
                    st.error("DWR form check failed — missing: "
                             + ", ".join(missing)
                             + ". The pre-filled report may no longer work; "
                               "re-read the form's entry IDs.")
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
        signed_in_via_oidc = False
        if _oidc_active():
            try:
                signed_in_via_oidc = bool(_st_user().is_logged_in)
            except Exception:
                signed_in_via_oidc = False  # nothing to clear; just rerun
        if signed_in_via_oidc:
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
         "Calendar", "Map", "Export", "Privacy & Data"],
    )

    # Leaving a page ends whatever was on it. Without this, saving a trip and
    # wandering off to the Dashboard left "Trip saved" waiting on Log a Session
    # — come back an hour later to log a second outing and you are greeted by
    # the receipt for the first one instead of a blank form.
    if st.session_state.get("_last_page") != page:
        st.session_state["_last_page"] = page
        for _k in ("log_saved_msg", "pending_dwr_sid"):
            st.session_state.pop(_k, None)

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
                # Export-first gate: user must grab a FULL backup (ZIP with
                # sessions + fish + spots + restorable JSON — not just a
                # sessions CSV) before the delete button unlocks.
                got_backup = st.download_button(
                    "⬇️ Step 1 — Download full backup (ZIP)",
                    data=backup_io.build_zip_bytes(),
                    file_name=f"fishing_log_backup_{date.today().isoformat()}.zip",
                    mime="application/zip",
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
        "Privacy & Data": page_privacy,
    }[page]()

    guide = _user_guide_bytes()
    if guide:
        st.sidebar.download_button(
            "📖 User Guide (PDF)", guide,
            file_name="Fishing_Log_User_Guide.pdf", mime="application/pdf",
            use_container_width=True,
        )
    st.sidebar.caption(f"build {APP_BUILD}")
    _mobile_sidebar_autoclose()


def _mobile_sidebar_autoclose():
    """On phone-width screens, close the sidebar overlay after a nav item is
    tapped — otherwise the new page renders hidden behind the menu. Desktop
    (>640px) is untouched. Installed once per browser page via a parent-window
    flag; survives Streamlit reruns because the listener lives on the parent
    document, which is never replaced."""
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        (function () {
          // This script runs inside a component iframe that Streamlit destroys
          // and recreates on every rerun — a listener registered from here dies
          // with the iframe (works once, then never again). So instead, inject
          // the listener as a <script> element into the PARENT page itself: it
          // then lives in the parent's JS realm and survives all reruns.
          // Written as a real function, then serialized with .toString() into a
          // <script> tag in the parent page — avoids quote-escaping bugs and
          // runs entirely in the parent realm.
          function parentCode() {
            function collapse(attempt) {
              var sb = document.querySelector('section[data-testid="stSidebar"]');
              if (!sb) return;
              if (sb.getAttribute('aria-expanded') === 'false') return;
              var btn = sb.querySelector('[data-testid="stSidebarCollapseButton"] button');
              if (btn) btn.click();
              if (attempt < 6) setTimeout(function () { collapse(attempt + 1); }, 300);
            }
            document.addEventListener('click', function (e) {
              if (window.innerWidth > 640) return;
              var sb = document.querySelector('section[data-testid="stSidebar"]');
              if (!sb || !sb.contains(e.target)) return;
              if (!e.target.closest('label') || !e.target.closest('div[role="radiogroup"]')) return;
              setTimeout(function () { collapse(0); }, 200);
            }, true);
          }
          const P = window.parent;
          if (P.__flSidebarAutoClose) return;
          P.__flSidebarAutoClose = true;
          const s = P.document.createElement('script');
          s.textContent = '(' + parentCode.toString() + ')();';
          P.document.body.appendChild(s);
        })();
        </script>
        """,
        height=0,
    )


if __name__ == "__main__":
    main()
