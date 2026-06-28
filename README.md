# 🎣 Fishing Log

A local, offline fishing-session tracker. Log each trip's conditions and catches,
browse and search past sessions, see success-rate analytics, and plot your spots
on an interactive map color-coded by how well you did. All data is stored in a
local SQLite database — no internet required to log or analyze.

## Features

- **Data entry** — date, start/end time (hours auto-computed), location + GPS
  coordinates, weather, air/water temperature, bait/lure, and **multiple species
  with counts** per session.
- **Browse & search** — filter by date range, location, and species; drill into
  any session for full conditions (e.g. "where did I fish on a given day last year
  and what were the conditions?").
- **Analytics** — sortable summary tables of success rate, fish/hour, and totals by
  **time of year, location, species, and weather**.
- **Map** — Folium interactive map; markers colored red (skunked) / orange (1–4) /
  green (5+). Exportable as a standalone `map.html`.
- **Streamlit UI** — runs locally in your browser.

## Project layout

```
app.py                  Streamlit UI (thin presentation layer)
fishing_log/
  database.py           SQLite connection, schema, low-level CRUD
  data_entry.py         add/update/delete + validation
  search.py             browse & filtered queries
  analytics.py          summary tables (pandas)
  map_view.py           Folium map builder
  seed.py               sample data
tests/                  pytest suite
data/fishing_log.db     created on first run
```

## Setup

Requires Python 3.9+.

```bash
cd "Fish APP"
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

This opens the app in your browser. On first launch the database is created
automatically; use **Load sample data** in the sidebar (or run
`python -m fishing_log.seed`) to populate ~18 example sessions.

## Tests

```bash
pip install pytest
pytest
```

## Notes on "offline"

Logging, searching, and all analytics work with **no network connection**. The map
page draws its background tiles from OpenStreetMap, which needs internet to *display*
the basemap — but your session data and the markers themselves are entirely local.
