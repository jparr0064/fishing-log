# Code Review — Fishing Log (2026-07-02)

Full audit of the app after the migration from local single-user SQLite to
multi-user Supabase Postgres (Streamlit Community Cloud). Reviewed: `app.py`,
all `fishing_log/` modules, tests, config, git history. Test suite was run.

**Context for whoever picks this up:** the code quality is good — clean
layering, parameterized SQL, sensible validation. Nearly every problem below
exists because the app changed identity (local → multi-user cloud) and parts
of the codebase haven't caught up. Constraint: **keep it Streamlit** (pinned
`streamlit==1.42.0`).

---

## 🔴 P0 — Broken right now

### ~~1. Entire test suite fails (38/38 errors)~~ ✅ Fixed 2026-07-02
Rebuilt against SQLAlchemy `sqlite:///:memory:` engine. Fixture monkeypatches
`db.get_engine`, `db.get_current_user`, and `db.set_current_user`. Ported
`ILIKE` → `LOWER LIKE`, moved `STRING_AGG` species_list to Python
post-processing, removed `::numeric` casts, fixed `calendar_month` EXTRACT →
Python string parse. Deleted tests for removed features (photos, backups,
SQLite migrations). Added `test_write_scoping` for IDOR fixes. **31/31 passing.**

### ~~2. Every user's DWR report pre-fills YOUR email~~ ✅ Fixed 2026-07-02
Dropped `emailAddress` param from `prefilled_url` entirely; removed `ANGLER_EMAIL`
constant. The Google Form collects the email from the signed-in Google account.

### ~~3. Map page "Export standalone map.html" is dead~~ ✅ Fixed 2026-07-02
Replaced `st.button` + `save_map` with `st.download_button` using
`fmap.get_root().render()` — serves rendered HTML directly to the browser.

### ~~4. CLAUDE.md, README.md, `fishing_log/__init__.py` describe the old app~~ ✅ Fixed 2026-07-02
All three rewritten for the real architecture (Supabase Postgres via SQLAlchemy,
`user_email` scoping rule, demo mode, secrets setup, OIDC deploy notes, SQLite
test instructions + portability rules). CLAUDE.md now leads with the user-scoping
rule and the local→cloud migration history. Documented the streamlit==1.42.0 pin
vs. drifted local venv.

---

## 🟠 P1 — Security (multi-user raises the bar)

### ~~1. Auth is honor-system~~ ✅ Fixed 2026-07-02
Replaced `st.experimental_user` (removed in 1.38+) with `st.login("google")` /
`st.user`. `_oidc_active()` checks `hasattr(st.user, "is_logged_in")` — True
only when `[auth]` is in `secrets.toml` (production). In that mode the login
page shows a Google button; local dev still uses the email form fallback.
Sign-out calls `st.logout()` for OIDC users, `st.rerun()` otherwise.
Demo shortcut (`DEMO_EMAIL` in session_state) bypasses auth in both modes.
**Note:** needs `[auth]` section in secrets.toml with `redirect_uri`,
`cookie_secret`, and `[auth.google]` client credentials to activate on Cloud.

### ~~2. Writes are not user-scoped (IDOR)~~ ✅ Fixed 2026-07-02
- `db.get/set_current_user` now use `st.session_state` instead of `threading.local` — safe for widget callbacks.
- `update_session`, `delete_session`, `set_dwr_filed` all have `AND user_email = :email`.
- `insert_fish` / `insert_spots` call `_assert_session_owned()` (SELECT 1 ownership check) before inserting.

### 3. Stored HTML injection (minor)
`unsafe_allow_html=True` interpolates user text in: trip cards
(`_trip_card`: `location_name`, `species_list`), dashboard recent trips, and
the calendar (`trip-loc` div). Mostly self-XSS, but demo-admin edits render
for every demo viewer.
**Fix:** `html.escape()` at the 3–4 injection points.

---

## 🟡 P2 — Highest-impact improvements

1. **Rebuild tests** (P0 #1) — the enabler for everything else.
2. **Fix auth + write-scoping together** (P1 #1–2) — the most important fix
   for the deployed app.
3. ~~**Delete dead code**~~ ✅ Done 2026-07-02
   - `git rm`'d: `fishing_log/media.py`, `fishing_log/backup.py`,
     `fishing_log/seed.py`, `app_full.py` (media/backup were only referenced
     by app_full; seed only by README).
   - `rm`'d untracked one-off scripts: `migrate_photos.py`, `migrate_shad.py`,
     `check_photos_table.py`.
   - **Kept** `seed_demo.py` — self-contained live demo seeder (imports only
     `database` + `data_entry.moon_phase_name`, not the deleted `seed`).
   - Verified: app.py compiles, seed_demo.py parses, 31/31 tests pass.
4. ~~**Rewrite CLAUDE.md/README** (P0 #4).~~ ✅ Done 2026-07-02 (+ `__init__.py`).
5. **Data safety + performance:** ✅ Done 2026-07-02
   - ~~"Clear my data" = one checkbox → irreversible `DELETE`~~ → now an
     **export-first gate**: Step 1 download-CSV button unlocks Step 2 confirm,
     which unlocks the delete button. No accidental one-click wipe.
   - ~~Dashboard fires ~8 uncached queries per rerun~~ → dashboard now reads
     through cached wrappers (`_cached_overall_stats`, `_cached_personal_bests`,
     `_cached_year_over_year`, `_cached_by_month`, `_cached_sessions`), so reruns
     don't re-query. (Within a single first render, `_session_frame` is still
     computed per analytics fn — deeper dedup left as a future refactor.)
   - ~~`_refresh()` calls `st.cache_data.clear()` — nukes ALL users~~ → now
     bumps a per-user `_cache_ver` in `st.session_state` that's part of every
     cache key; only the writer's reads invalidate. Added `ttl=300` to evict
     orphaned entries.

---

## ⚪ P3 — Small stuff, no urgency

- ~~Clearing all spots while editing nulls the session's lat/lon.~~ ✅ Fixed
  2026-07-02 — `update_session` now omits lat/lon from the UPDATE when no spots
  are provided, preserving the stored coords. Regression test added.
- ~~Air/water temp inputs pre-fill 70°/60°.~~ ✅ Fixed 2026-07-02 — both forms
  now default blank (`value=None`, `placeholder="optional"`); a reading is only
  stored if the angler enters one.
- **Spot-picker zoom resets to 15 after each click-rerun.** ⏸ Deferred — the
  fix needs `zoom` added to `returned_objects` + written to `zoom_key`, but the
  surrounding code deliberately excludes zoom/center to avoid a Leaflet
  click-miss bug (see the comment at `_spots_picker`). Cosmetic; not worth the
  interactive-behavior regression risk (can't be unit-tested).
- ~~`ORDER BY s.start_time DESC` with NULL start_times orders oddly.~~ ✅ Fixed
  2026-07-02 — `list_sessions` now `ORDER BY s.date DESC, (s.start_time IS NULL),
  s.start_time DESC` (nulls last, portable across SQLite/Postgres).
- Secrets hygiene is GOOD: `.streamlit/secrets.toml` never committed
  (verified in git history); keep it that way.

---

## Suggested order of work

1. ~~P0 #2 (DWR email) + P0 #3 (map export)~~ ✅ Done 2026-07-02.
2. ~~P1 #2 groundwork: move user context to `st.session_state`, then scope all writes.~~ ✅ Done 2026-07-02.
3. ~~P0 #1: rebuild tests against the corrected behavior.~~ ✅ Done 2026-07-02.
4. ~~P1 #1: real auth (`st.login` OIDC)~~ ✅ Done 2026-07-02.
5. ~~P2 #3–4: dead-code deletion + doc rewrite.~~ ✅ Done 2026-07-02.
6. ~~P2 #5 and P3 as time allows.~~ ✅ Done 2026-07-02 (except spot-picker zoom,
   deferred with rationale — see P3).

After each change to `fishing_log/*`, remember Streamlit doesn't reload
package modules on browser refresh — restart the app process.
