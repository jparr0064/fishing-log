# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **multi-user cloud** fishing-log app, focused on **striper** fishing and
**trolling** at Smith Mountain Lake, VA. Streamlit UI over a **Supabase Postgres**
database, deployed on **Streamlit Community Cloud**. Each angler signs in and sees
only their own data. There is also a read-only **demo** account with sample trips.

> **History:** this began as a local single-user SQLite app. It was migrated to
> Supabase Postgres for multi-user cloud hosting. If you find references to local
> SQLite, photos, on-disk backups, or `data/fishing_log.db`, they are leftovers —
> those features were removed in the migration. See `REVIEW.md` for the audit that
> drove the cleanup.

## The one rule that matters most

**Every query must be scoped to the current user.** All data is isolated by
`user_email`. Reads filter `WHERE user_email = :email`; writes (UPDATE/DELETE)
filter `AND user_email = :email`; child inserts (`insert_fish`/`insert_spots`)
verify session ownership first via `db._assert_session_owned()`. The current user
comes from `db.get_current_user()`, which reads `st.session_state["user_email"]`
(set once in `main()` via `db.set_current_user()`).

**Do not** use `threading.local` for user context — widget callbacks run on a
different thread than `main()`, so a thread-local would be empty in callbacks and
silently unscope the write. This was fixed; keep it in `st.session_state`.

## Environment & commands

This machine has **no `python` on PATH** (only the Windows Store stub). Always use
the venv interpreter directly:

- Run app: `.venv/Scripts/streamlit.exe run app.py --server.port 8765` (the desktop
  **Fishing Log** shortcut → `Fishing Log.bat` does this). Pinned to **port 8765**.
- All tests: `.venv/Scripts/python.exe -m pytest tests -q`
- Single test: `.venv/Scripts/python.exe -m pytest tests/test_fishing_log.py::test_write_scoping -q`
- Compile-check: `.venv/Scripts/python.exe -m py_compile app.py`
- First-time setup: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt pytest`

**Streamlit version:** `requirements.txt` pins `streamlit==1.42.0` (what Streamlit
Cloud installs; native auth `st.login`/`st.user` landed in 1.42.0). The local
`.venv` has drifted to a newer version — usually harmless, but if something
"works locally, breaks on Cloud," suspect the gap.

**Secrets** (`.streamlit/secrets.toml`, git-ignored — never commit):
- `database_url` — Supabase Postgres connection string (SQLAlchemy/psycopg2 URL).
  `_bootstrap()` copies it into `os.environ["DATABASE_URL"]`, which `get_engine()` reads.
- `dev_user_email` — the owner's email; when signed in as this address, a sidebar
  "🛠 Edit demo data" toggle appears so the demo account can be edited.
- `[auth]` + `[auth.google]` — **optional**; present them to enable Google OIDC
  (see Auth below). Absent locally → the app falls back to a plain email form.

**Sibling app / port collisions:** a separate **Wardrobe** app at `C:\CLAUDE\Fashion`
(own venv, pinned to **port 8766**). Both default to Streamlit's 8501, which
previously caused the fishing app's browser tab to open the wardrobe app. Each
launcher pins its own port — keep it that way.

**Shell note:** use the **Bash tool** for `python -c "..."` one-liners and `curl` —
PowerShell mangles embedded quotes and PowerShell 5.1 lacks `?:`/`&&`. PowerShell is
fine for `streamlit run`, `pip`, process management, and health-checks.

### Verifying changes
- **Unit tests** for all data/logic (see Tests below). They run against an in-memory
  SQLite engine, so keep SQL **portable** (see "SQLite vs Postgres" below).
- **Headless render test** via `streamlit.testing.v1.AppTest` is possible but note
  the app requires `DATABASE_URL` + a signed-in user; interactive components
  (`st_folium`, `streamlit_geolocation`) render as `UnknownElement`.
- **Live health check**: `streamlit run app.py --server.headless=true --server.port=NNNN`,
  then GET `http://localhost:NNNN/_stcore/health` (expect `200 ok`). Stop the server after.

**⚠ Do not run destructive probes against the live Supabase DB.** It holds real
users' trips. `db.delete_all_sessions()` is scoped to the current user but still
irreversible. Test data logic against the in-memory SQLite suite instead.

## Architecture

Layered: `app.py` is a **thin Streamlit presentation layer** over the `fishing_log`
package. Keep logic in the package.

- `database.py` — SQLAlchemy engine (Supabase Postgres via psycopg2), user context
  (`get/set_current_user` → `st.session_state`), `SESSION_FIELDS`, low-level CRUD.
  `insert_session`, `insert_fish`/`insert_spots` (both call `_assert_session_owned`),
  `session_count`, `delete_all_sessions`. Legacy no-op stubs (`init_db`,
  `set_db_path`, `get_db_path`) remain so nothing import-breaks; `DATA_DIR`/
  `PROJECT_ROOT` are `/tmp` stubs.
- `data_entry.py` — validation + `add_session`/`update_session`/`delete_session`/
  `set_dwr_filed` (**all user-scoped**). Holds `WEATHER_OPTIONS`, `FISHING_STYLES`,
  `BAIT_LURE_OPTIONS`, `moon_phase_name`. `validate_fish` accepts per-fish dicts
  **or** legacy `{species,count}` (expands to N rows). `update_session(..., spots=None)`
  leaves spots untouched; a list replaces them.
- `search.py` — read queries → pandas, all scoped to `db.get_current_user()`.
  `list_sessions`, `get_session`, `map_rows`, `caught_spot_points`, `calendar_month`,
  `fish_export`, `recent_defaults`, `baits_by_frequency`, `distinct_*`. `species_list`
  ("Bass (3), Striper (1)") is built in Python by `_species_list_map`, not SQL.
- `analytics.py` — pandas summaries. `_session_frame()` / `_fish_with_dates()` are the
  shared bases. Monthly, sizes, personal bests, moon phase, year-over-year, and
  "what's working" condition insights (`by_water_temp`, `by_time_of_day`,
  `by_fishing_style`, `by_bait`, `by_weather`, `by_moon_phase`, `best_conditions`).
- `map_view.py` — Folium. `SUCCESS_TIERS` (Skunked=black / Good=red / Great=yellow /
  Blowout=blue), `build_map`, `build_route_map`/`draw_route` (trolling route: AntPath
  + numbered DivIcon markers, 🐟 for caught spots), `add_heatmap`, `DEFAULT_CENTER`/
  `DEFAULT_ZOOM` (Smith Mountain Lake).
- `dwr_report.py` — builds the **pre-filled Google Form URL** for the VA DWR "Striped
  Bass Angler Journal". Form `entry.*` IDs are hardcoded constants. **No email is
  prefilled** — the Google Form collects it from the signed-in Google account.
  Sizes use the `"` inch symbol; harvested = `N/A` when zero kept. Stripers only.

### Data model (Supabase Postgres)
- `sessions` — trip-level fields incl. `user_email`, `weather`, `air_temp`,
  `water_temp`, `bait_lure`, `fishing_style`, `num_anglers`, `dwr_filed`, `moon_phase`,
  `latitude/longitude` (the **starting** spot), `notes`.
- `fish` — **one row per fish** (`species`, `length`, `weight`, `kept`, `depth`).
  Zero rows = skunked.
- `spots` — one or more map pins per session for trolling (`latitude`, `longitude`,
  `label`, `caught`). The session's `latitude/longitude` = first spot.
- All children FK to `sessions(id)` with `ON DELETE CASCADE`.
- **Schema lives in Supabase**, not in code. `init_db()` is a no-op stub — there is
  no in-app migration system anymore. To add a column: alter the table in Supabase,
  then mirror it in the `sessions` handling (`SESSION_FIELDS` / `validate_session`).
  One-off schema changes were done via throwaway scripts (since deleted).

### SQLite vs Postgres (tests run on SQLite)
The app runs on Postgres but tests use in-memory SQLite, so **keep SQL portable**:
- Use the `_like()` helper (`LOWER(col) LIKE LOWER(:p)`), not Postgres `ILIKE`.
- Don't use `STRING_AGG`, `::` casts, or `EXTRACT(... FROM x::date)` — do that
  aggregation/parsing in Python (see `search._species_list_map`, `calendar_month`).
- `ROUND(AVG(...), 2)` works on both; `ROUND(x::numeric, 2)` does not.

## Auth
- **Production (Cloud):** when `[auth]`/`[auth.google]` are in secrets, `_oidc_active()`
  is true (detected via `hasattr(st.user, "is_logged_in")`). Login shows a Google
  button (`st.login("google")`); `st.user.email` is the identity. Sign-out calls
  `st.logout()`.
- **Local dev:** no `[auth]` configured → a plain email form (honor-system, dev only).
- **Demo:** the "Try the Demo →" button sets `st.session_state["user_email"]` to
  `DEMO_EMAIL` and bypasses auth in both modes. Demo is read-only unless the
  `dev_user_email` owner flips the sidebar "Edit demo data" toggle.

## Critical conventions (easy to get wrong)

- **Streamlit module reloading:** a browser refresh re-runs `app.py` but does **not**
  reload imported `fishing_log/*` modules. After editing the package, the user must
  **fully restart** the app (kill the process). Tell them when package files change.
- **User context is per-session, in `st.session_state`** — not thread-local. See "The
  one rule" above.
- **Interactive widgets must live OUTSIDE `st.form`** (spot picker, etc.) and stage
  results in `st.session_state`; the submit handler reads them.
- **`st_folium` keeps `use_container_width=`** (its `width` means pixels). Other
  elements use `width="stretch"`.
- **Map markers are Leaflet-drawn** (`CircleMarker` / `DivIcon`), never `folium.Marker`
  (its PNG icon breaks inside the st_folium iframe).
- **Color-blind user:** use the **`CB_PALETTE`** (Okabe-Ito) in charts and never rely
  on color alone — pair with labels/shapes (numbered route markers, 🐟 icons, N/A text).
- **`_refresh()` clears `st.cache_data`** after a write. Note it currently clears the
  cache for **all** users (a known perf issue flagged in REVIEW.md P2 #5).
- **Single-lake assumptions:** location/species defaults are constants in `app.py`.
- **Offline scope is gone:** the app needs the network (Supabase + Folium tiles).

## App pages (in `app.py`)
Dashboard (KPIs, personal bests, DWR-unfiled nudge, recent trips) · Log a Session
(spot picker, per-fish editor with Kept?) · Browse & Search (trip **cards** + full
detail with route map, DWR report + filed toggle, edit, delete) · Analytics (Monthly /
Sizes / Personal Bests / **What's working**) · Calendar (per-day trips + moon phase) ·
Map (per-session dots + **catch hotspot heatmap** toggle; download standalone map.html) ·
Export (CSV downloads of sessions and per-fish data + "Clear my data").

## Tests
`tests/test_fishing_log.py` — an autouse fixture creates a fresh in-memory SQLite
engine per test (via `create_engine("sqlite:///:memory:")` with the schema DDL and
FK pragma), then monkeypatches `db.get_engine`, `db.get_current_user`, and
`db.set_current_user`. All tests run scoped to a fixed `TEST_EMAIL`.
`test_write_scoping` inserts a row as another user and asserts update/delete/
set_dwr_filed cannot touch it. When adding data logic, add a test here and keep the
SQL SQLite-compatible.

## Status & roadmap
See `REVIEW.md` for the current audit and the remaining P2/P3 items (cache
invalidation scope, "Clear my data" safety, air/water temp default pre-fill, minor
ordering/zoom nits). Water-temp auto-fetch and packaged-folder distribution are older
ideas from the local era and may no longer apply to the cloud version.
