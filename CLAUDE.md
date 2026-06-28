# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, offline fishing-log app for one angler on one lake (Smith Mountain Lake, VA), focused on **striper** fishing and **trolling**. Streamlit UI over a SQLite database; all data and photos live on disk — no server, no account. See `README.md` for the user-facing feature list.

## Environment & commands

This machine has **no `python` on PATH** (only the Windows Store stub). Always use the venv interpreter directly:

- Run app: `.venv/Scripts/streamlit.exe run app.py --server.port 8765` (the desktop **Fishing Log** shortcut → `Fishing Log.bat` does this). The app is pinned to **port 8765**.
- All tests: `.venv/Scripts/python.exe -m pytest tests -q`
- Single test: `.venv/Scripts/python.exe -m pytest tests/test_fishing_log.py::test_dwr_summarize_and_url -q`
- Compile-check: `.venv/Scripts/python.exe -m py_compile app.py`
- First-time setup: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt pytest`

**Sibling app / port collisions:** there's a separate **Wardrobe** app at `C:\CLAUDE\Fashion` (its own venv, pinned to **port 8766**). Both default to Streamlit's 8501, which previously caused the fishing app's browser tab to open the wardrobe app. That's why each launcher pins its own port — keep it that way.

**Shell note:** use the **Bash tool** for `python -c "..."` one-liners and `curl` — PowerShell mangles embedded quotes, and PowerShell 5.1 lacks `?:`/`&&`. PowerShell is fine for `streamlit run`, `pip`, process management, and health-checks. Note `/tmp` in Git Bash ≠ where the Windows venv python looks — write probe files into the project dir (and clean them up).

### Verifying changes
- **Unit tests** for all data/logic (see Tests below).
- **Headless render test** via `streamlit.testing.v1.AppTest`: `AppTest.from_file("app.py").run()`, then `at.sidebar.radio[0].set_value("<page>").run()` and assert `not at.exception`. Catches per-page runtime errors. Interactive components (`st_folium`, `st_cropper`, `streamlit_geolocation`) can't be driven by AppTest — they render as `UnknownElement`. **AppTest `session_state` has no `.get()`** — use `"key" in at.session_state` / `at.session_state["key"]`.
- **Live health check**: `streamlit run app.py --server.headless=true --server.port=NNNN`, then GET `http://localhost:NNNN/_stcore/health` (expect `200 ok`). Always stop the test server afterward so the port stays free.

When writing throwaway probe scripts, **inspect the DB before deleting rows** — `data/fishing_log.db` holds the user's real trips. Delete by a distinctive predicate, never `delete_all_sessions()`. A manual backup and rolling auto-backups live in `data/backups/`.

## Architecture

Layered: `app.py` is a **thin Streamlit presentation layer** over the `fishing_log` package. Keep logic in the package.

- `database.py` — connection, schema, low-level CRUD, **migrations**. `SESSION_FIELDS` drives generic session insert/update. `set_db_path()` lets tests point elsewhere. `insert_fish`/`insert_spots`/`insert_photo`.
- `data_entry.py` — validation + `add_session`/`update_session`/`delete_session`/`set_dwr_filed`. Holds `WEATHER_OPTIONS`, `FISHING_STYLES`. `validate_fish` accepts per-fish dicts **or** legacy `{species,count}` (expands to N rows). `update_session(..., spots=None)` leaves spots untouched when `spots is None`, replaces them otherwise.
- `search.py` — read queries → pandas. `list_sessions` (cards/table, incl. `biggest_length`, `dwr_filed`), `get_session` (full detail incl. `fish`, `spots`), `map_rows` (one **starting** dot per session), `caught_spot_points` (heatmap), `recent_defaults`, `baits_by_frequency`, `fish_export`.
- `analytics.py` — pandas summaries. `_session_frame()` is the shared base. Monthly (`by_month`), sizes (`size_by_month`, `fish_sizes`), `personal_bests`, and **"what's working"** condition insights (`by_water_temp`, `by_time_of_day`, `by_fishing_style`, `by_bait`, `by_weather`, `best_conditions`).
- `map_view.py` — Folium. `SUCCESS_TIERS` (catch-success colors, user-chosen black/red/yellow/blue), overview `build_map` (per-session dot + date/time/fish tooltip), `build_route_map`/`draw_route` (per-session trolling route: `AntPath` direction line + numbered `DivIcon` markers, 🐟 for caught spots), `add_heatmap` (catch hotspots), `DEFAULT_CENTER`/`DEFAULT_ZOOM`.
- `media.py` — photos. `load_image_oriented` applies **EXIF orientation** (fixes sideways phone photos). Files under `data/photos/<session_id>/`; `photos` table stores paths **relative to `PROJECT_ROOT`**.
- `dwr_report.py` — builds the **pre-filled Google Form URL** for the VA DWR "Striped Bass Angler Journal". Form field `entry.*` IDs + the email `emailAddress` param are hardcoded constants. Sizes use the `"` inch symbol; harvested = `N/A` when zero kept. Stripers only.
- `backup.py` — `auto_backup` (startup, keeps 10), `list_backups`, `restore_backup`; CSV export uses `search` DataFrames.
- `seed.py` — sample multi-lake data; **not** used in the UI (single-lake app). Kept for tests/manual use.

### Data model (current)
- `sessions` — trip-level fields incl. `weather`, `air_temp`, `water_temp`, `bait_lure`, `fishing_style`, `num_anglers`, `dwr_filed`, `latitude/longitude` (the **starting** spot), `notes`.
- `fish` — **one row per fish** (`species`, `length`, `weight`, `kept`). Zero rows = skunked. This replaced the old aggregate `catches` table.
- `spots` — one or more map pins per session for trolling (`latitude`, `longitude`, `caught`). The session's `latitude/longitude` = first spot.
- `photos` — image paths per session.
- `catches` — **LEGACY**, kept as a read-only backup after the per-fish migration; not written to.
- All children cascade-delete; foreign keys enabled per connection.

### Migrations are additive-only (never drop/rename)
`init_db()` runs `CREATE TABLE IF NOT EXISTS`, then `_ensure_columns()`:
- `_add_columns(table, {...})` adds missing columns to `sessions`/`spots`/`fish` (guarded by table existence).
- **Version-guarded one-time backfills** via `PRAGMA user_version`: v1 expands `catches`→`fish`; v2 seeds `spots` from each session's lat/long. These run **exactly once**.
To add a session column: add to the `sessions` DDL, to `SESSION_FIELDS`, to the `sessions` `_add_columns` dict — and default it in `validate_session` if `NOT NULL` (else inserts fail on `None`).

## Critical conventions (easy to get wrong)

- **Streamlit module reloading:** a browser refresh re-runs `app.py` but does **not** reload imported `fishing_log/*` modules. After editing the package, the user must **fully restart** the app (kill the process). Tell them when package files change.
- **Interactive widgets must live OUTSIDE `st.form`.** The spot picker (`_spots_picker`) and photo workbench (`_photo_workbench`/`_photo_editor`) are outside the form and stage results in `st.session_state` (`spots`, `pending_photos`); the submit handler reads them.
- **Read checkbox/toggle state BEFORE drawing a map that depends on it.** In `_spots_picker`, each spot's `caught` flag is synced from its checkbox `session_state` *above* the map render, so a just-toggled box recolors the map the same run. Clean up per-spot widget keys on remove/clear (see `_clear_spot_state`).
- **st_folium view persistence:** the spot picker stores returned `zoom`/`center` in `session_state` and feeds them back as the map's `zoom_start`/`location` so interacting/saving doesn't reset the zoom.
- **`st_folium` keeps `use_container_width=`** (its `width` means pixels). Other elements use `width="stretch"`.
- **Map markers are Leaflet-drawn** (`CircleMarker` / `DivIcon`), never `folium.Marker` (its PNG icon breaks inside the st_folium iframe). `st_cropper`'s key includes a version counter so it refreshes after each rotate.
- **Color-blind user:** use the **`CB_PALETTE`** (Okabe-Ito) in charts and never rely on color alone — pair with labels/shapes (numbered route markers, 🐟 icons, N/A text).
- **Single-lake assumptions:** location/species filters are fixed lists (`DEFAULT_LOCATION`, `SPECIES`); defaults are constants in `app.py` (`DEFAULT_LAT/LON`, `DEFAULT_FROM_DATE`).
- **Offline scope:** logging/search/analytics work offline; only Folium **basemap tiles** need internet. HEIC phone photos won't display (accept jpg/png/gif/bmp/webp).

## App pages (in `app.py`)
Dashboard (KPIs, personal bests, DWR-unfiled nudge, recent trips) · Log a Session (spot picker, photo workbench, per-fish editor with Kept?) · Browse & Search (trip **cards** + **Photo gallery** tab + full detail with route map, DWR report+filed toggle, edit, delete) · Analytics (Monthly / Sizes / Personal Bests / **What's working**) · Map (per-session dots + **catch hotspot heatmap** toggle) · Backup & Export.

## Tests
`tests/test_fishing_log.py` — autouse fixture runs against `:memory:` SQLite by monkeypatching `get_connection` with a non-closing proxy. Filesystem tests (photos) monkeypatch `db.PHOTOS_DIR` to a temp dir **under `PROJECT_ROOT`** (so stored relative paths resolve). Migration/backfill tests build hand-made old-schema DBs and call `init_db(conn)` / `db._ensure_columns(conn)` directly.

## Status & roadmap

**Done:** core logging; per-fish length/weight/kept; trolling multi-spot routes with caught markers; photos (EXIF/rotate/crop/gallery); Browse cards; themed/color-blind-safe UI; Dashboard home; analytics (monthly, sizes, personal bests, "what's working" condition insights); overview map + catch hotspot heatmap; DWR striper-report pre-fill + filed/not-filed tracking; backups/CSV/restore; desktop launchers with icons (fish/shirt) on dedicated ports.

**Next / open:**
- **Water-temp auto-fetch button** (Log page) — best-effort scrape from the SML app's data (`app.sml.plus` / `sml.today`); **no official API** (USGS gauge 02057400 has no temperature). Online-only convenience with manual fallback. Not yet built.
- **Packaged-folder distribution** ("option 1") so others can run their own copy: a zip with a `setup.bat` (installs Python via winget if missing, builds venv, installs requirements), a launcher, and a README — **excluding** the user's `data/` (db, photos, backups). A scheduled reminder (`remind-package-fishing-log`) fires ~2026-06-28.
- Possible later: tie individual fish to specific spots; avg fish **size** by condition in "what's working"; mobile/quick-log entry; season goals / year-over-year.
