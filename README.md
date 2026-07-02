# 🎣 Fishing Log

A **multi-user cloud** fishing-session tracker, focused on **striper** fishing and
**trolling** at Smith Mountain Lake, VA. Log each trip's conditions and catches,
browse and search past sessions, see success-rate analytics, and plot your trolling
routes and catch hotspots on an interactive map. Each angler signs in and sees only
their own data.

Built with **Streamlit** over a **Supabase Postgres** database, deployed on
**Streamlit Community Cloud**.

## Features

- **Log a session** — date, start/end time (hours auto-computed), location + GPS,
  weather, air/water temperature, bait/lure, fishing style, number of anglers, moon
  phase (auto), notes, one or more map **spots** (trolling route), and **one row per
  fish** with length, weight, depth, and whether it was kept.
- **Browse & search** — filter by date range, location, and species; drill into any
  session for full detail with its trolling route map.
- **Analytics** — monthly trends, size distributions, personal bests, and a
  **"what's working"** view (success by water temp, time of day, fishing style, bait,
  weather, moon phase).
- **Calendar** — month grid of trips with catch counts and moon phase.
- **Map** — Folium map with per-session dots color-coded by catch success
  (Skunked / Good / Great / Blowout) and a catch-hotspot heatmap toggle. Download a
  standalone `map.html`.
- **DWR report** — one click pre-fills the Virginia DWR "Striped Bass Angler Journal"
  Google Form for a striper trip, and tracks which trips you've filed.
- **Export** — download your sessions and per-fish data as CSV (also your backup).
- **Demo account** — try it with 15 sample Smith Mountain Lake striper trips.

## Project layout

```
app.py                  Streamlit UI (thin presentation layer)
fishing_log/
  database.py           SQLAlchemy engine, user scoping, low-level CRUD
  data_entry.py         add/update/delete + validation (user-scoped)
  search.py             browse & filtered read queries
  analytics.py          summary tables (pandas)
  map_view.py           Folium map builder
  dwr_report.py         VA DWR Google Form pre-fill
tests/                  pytest suite (runs on in-memory SQLite)
seed_demo.py            one-off seeder for the demo account
.streamlit/
  config.toml           theme + server config (committed)
  secrets.toml          DB + auth credentials (git-ignored)
```

Data lives in Supabase Postgres, isolated per user by `user_email`. There is no
local database file.

## Local development

Requires Python 3.9+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt pytest
```

Create `.streamlit/secrets.toml` (git-ignored) with at least:

```toml
database_url   = "postgresql+psycopg2://USER:PASSWORD@HOST:PORT/postgres"
dev_user_email = "you@example.com"   # enables the "Edit demo data" toggle
```

With no `[auth]` section, the app runs in **local-dev mode**: it shows a plain email
form to pick which user you are (no real authentication — dev only). Run it:

```bash
streamlit run app.py --server.port 8765
```

## Deploy to Streamlit Community Cloud

1. Push to GitHub and create the app on [share.streamlit.io](https://share.streamlit.io),
   pointing at `app.py`.
2. In the app's **Settings → Secrets**, add `database_url` and `dev_user_email` as
   above, plus a Google OIDC `[auth]` block to enable real sign-in:

   ```toml
   database_url   = "postgresql+psycopg2://..."
   dev_user_email = "you@example.com"

   # Approved sign-in emails (allowlist). The owner (dev_user_email) is always
   # allowed. Anyone signing in with a Google account NOT in this list is shown
   # a "request access" page with a demo button instead of a real account.
   # Omit this key to allow only the owner.
   allowed_emails = ["friend1@gmail.com", "friend2@gmail.com"]

   [auth]
   redirect_uri  = "https://your-app.streamlit.app/oauth2callback"
   cookie_secret = "a-long-random-string"

   [auth.google]
   client_id            = "...apps.googleusercontent.com"
   client_secret        = "..."
   server_metadata_url  = "https://accounts.google.com/.well-known/openid-configuration"
   ```

   Configure the Google OAuth client's authorized redirect URI to match
   `redirect_uri`. When `[auth]` is present the login screen shows a **Sign in with
   Google** button instead of the email form. To approve a new person later, add
   their email to `allowed_emails` in the app's Secrets — no redeploy needed.

3. The Supabase Postgres schema (`sessions`, `fish`, `spots`) must already exist —
   there is no in-app migration. To seed the demo account, run `python seed_demo.py`
   locally against the same `database_url`.

## Tests

```bash
pytest -q
```

The suite runs against an in-memory SQLite engine (fast, no network), so app SQL is
kept portable across SQLite and Postgres.

## Notes

- **Not offline** — the app needs the network for Supabase and for the map's
  OpenStreetMap basemap tiles.
- **Backups** — export your CSVs periodically; "Clear my data" is irreversible and
  there is no in-app backup.
