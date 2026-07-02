"""Seed 15 realistic Smith Mountain Lake striper trips for the demo account.

Run once:  .venv\Scripts\python.exe seed_demo.py
Idempotent — skips if demo data already exists.
"""
import os, sys, tomllib
from datetime import date as _date

with open(".streamlit/secrets.toml", "rb") as f:
    secrets = tomllib.load(f)
os.environ["DATABASE_URL"] = secrets["database_url"]

sys.path.insert(0, ".")
from fishing_log import database as db
from fishing_log.data_entry import moon_phase_name
from sqlalchemy import text

DEMO_EMAIL = "demo@fishinglog.demo"
engine = db.get_engine()

# Check if already seeded
with engine.connect() as conn:
    count = conn.execute(
        text("SELECT COUNT(*) FROM sessions WHERE user_email = :e"),
        {"e": DEMO_EMAIL}
    ).scalar()
if count and count >= 15:
    print(f"Demo data already present ({count} sessions). Nothing to do.")
    sys.exit(0)

# Clear any partial seed
with engine.begin() as conn:
    conn.execute(text("DELETE FROM sessions WHERE user_email = :e"), {"e": DEMO_EMAIL})
print("Cleared old demo data. Seeding 15 trips...")

# ---------------------------------------------------------------------------
# Trip definitions — 15 realistic SML striper sessions, April–July 2026
# ---------------------------------------------------------------------------
TRIPS = [
    # ---- April ----
    {
        "date": "2026-04-04", "start": "05:30", "end": "10:30",
        "location": "SML — Main Channel", "lat": 37.1646, "lon": -79.7091,
        "weather": "Sunny", "air": 58, "water": 62,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Fish stacked in 25 ft. Bite turned on right at first light.",
        "dwr": 1,
        "fish": [
            ("Striper", 24.0, 7.5, True,  18.0),
            ("Striper", 26.0, 9.0, True,  20.0),
            ("Striper", 19.0, 4.0, False, 15.0),
            ("Striper", 21.0, 5.5, False, 16.0),
            ("Striper", 22.0, 6.0, False, 18.0),
        ],
        "spots": [(37.1646, -79.7091), (37.1651, -79.7078)],
    },
    {
        "date": "2026-04-11", "start": "06:00", "end": "10:00",
        "location": "SML — Blackwater Arm", "lat": 37.1789, "lon": -79.6923,
        "weather": "Windy", "air": 52, "water": 59,
        "bait": "Jigging Spoon", "style": "Jigging", "anglers": 1,
        "notes": "Gusts to 25 mph. Couldn't hold position over the hump. Tough day.",
        "dwr": 0, "fish": [],
        "spots": [(37.1789, -79.6923)],
    },
    {
        "date": "2026-04-18", "start": "05:45", "end": "11:00",
        "location": "SML — Roanoke Arm", "lat": 37.1401, "lon": -79.7341,
        "weather": "Partly Cloudy", "air": 61, "water": 64,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Steady action mid-morning once we found the bait ball.",
        "dwr": 1,
        "fish": [
            ("Striper", 23.0, 6.5, True,  20.0),
            ("Striper", 18.5, 3.5, False, 14.0),
            ("Striper", 20.0, 5.0, False, 16.0),
        ],
        "spots": [(37.1401, -79.7341), (37.1388, -79.7356)],
    },
    {
        "date": "2026-04-25", "start": "05:00", "end": "10:00",
        "location": "SML — Main Channel", "lat": 37.1658, "lon": -79.7064,
        "weather": "Sunny", "air": 65, "water": 67,
        "bait": "Live Shad", "style": "Downlines", "anglers": 3,
        "notes": "Best day of the year so far. Limits before 9 AM. Shad were everywhere.",
        "dwr": 1,
        "fish": [
            ("Striper", 28.0, 11.0, True,  22.0),
            ("Striper", 25.0, 8.5,  True,  20.0),
            ("Striper", 27.0, 10.0, True,  21.0),
            ("Striper", 30.0, 13.5, True,  24.0),
            ("Striper", 20.0, 5.0,  False, 16.0),
            ("Striper", 19.0, 4.0,  False, 15.0),
            ("Striper", 22.0, 6.0,  False, 17.0),
            ("Striper", 21.0, 5.5,  False, 16.0),
        ],
        "spots": [(37.1658, -79.7064), (37.1663, -79.7051), (37.1671, -79.7039)],
    },
    # ---- May ----
    {
        "date": "2026-05-02", "start": "06:00", "end": "11:30",
        "location": "SML — Hales Ford Bridge", "lat": 37.1523, "lon": -79.7156,
        "weather": "Cloudy", "air": 64, "water": 68,
        "bait": "Umbrella Rig", "style": "Trolling", "anglers": 2,
        "notes": "Slow morning, picked up 2 nice fish trolling the point.",
        "dwr": 1,
        "fish": [
            ("Striper", 22.0, 6.0, True,  None),
            ("Striper", 20.5, 5.0, False, None),
        ],
        "spots": [(37.1523, -79.7156), (37.1534, -79.7143)],
    },
    {
        "date": "2026-05-09", "start": "05:30", "end": "09:30",
        "location": "SML — Main Channel", "lat": 37.1646, "lon": -79.7091,
        "weather": "Rain", "air": 57, "water": 66,
        "bait": "Jigging Spoon", "style": "Jigging", "anglers": 1,
        "notes": "Steady rain all morning. Fish just weren't there. Not the day for it.",
        "dwr": 0, "fish": [],
        "spots": [(37.1646, -79.7091)],
    },
    {
        "date": "2026-05-16", "start": "05:30", "end": "10:30",
        "location": "SML — Blackwater Arm", "lat": 37.1812, "lon": -79.6878,
        "weather": "Sunny", "air": 71, "water": 71,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Good steady bite. Water temp hitting the sweet spot.",
        "dwr": 1,
        "fish": [
            ("Striper", 25.0, 8.0, True,  22.0),
            ("Striper", 19.5, 4.5, False, 16.0),
            ("Striper", 18.0, 3.5, False, 14.0),
            ("Striper", 23.0, 6.5, False, 18.0),
        ],
        "spots": [(37.1812, -79.6878), (37.1821, -79.6861)],
    },
    {
        "date": "2026-05-23", "start": "05:00", "end": "09:30",
        "location": "SML — Main Channel", "lat": 37.1640, "lon": -79.7098,
        "weather": "Sunny", "air": 74, "water": 73,
        "bait": "Live Shad", "style": "Light Lines", "anglers": 2,
        "notes": "Surface bite at first light was unreal. Fish busting all around the boat.",
        "dwr": 1,
        "fish": [
            ("Striper", 24.0, 7.5,  True,  8.0),
            ("Striper", 29.0, 12.0, True,  6.0),
            ("Striper", 22.0, 6.0,  False, 5.0),
            ("Striper", 21.0, 5.5,  False, 4.0),
            ("Striper", 20.0, 5.0,  False, 6.0),
            ("Striper", 23.0, 6.5,  False, 5.0),
        ],
        "spots": [(37.1640, -79.7098), (37.1635, -79.7112), (37.1628, -79.7124)],
    },
    {
        "date": "2026-05-30", "start": "06:00", "end": "10:00",
        "location": "SML — Roanoke Arm", "lat": 37.1388, "lon": -79.7368,
        "weather": "Overcast", "air": 70, "water": 75,
        "bait": "Cut Bait", "style": "Downlines", "anglers": 1,
        "notes": "One fish late morning. Water is warming up — fish going deeper.",
        "dwr": 1,
        "fish": [
            ("Striper", 21.0, 5.5, False, 28.0),
        ],
        "spots": [(37.1388, -79.7368)],
    },
    # ---- June ----
    {
        "date": "2026-06-06", "start": "05:00", "end": "09:00",
        "location": "SML — Main Channel", "lat": 37.1655, "lon": -79.7073,
        "weather": "Sunny", "air": 78, "water": 77,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Early morning bite before the sun got up. Down 30 ft.",
        "dwr": 1,
        "fish": [
            ("Striper", 24.0, 7.5,  True,  30.0),
            ("Striper", 26.0, 9.5,  True,  30.0),
            ("Striper", 19.0, 4.0,  False, 28.0),
            ("Striper", 20.0, 5.0,  False, 30.0),
            ("Striper", 22.0, 6.0,  False, 32.0),
        ],
        "spots": [(37.1655, -79.7073), (37.1661, -79.7059)],
    },
    {
        "date": "2026-06-13", "start": "05:30", "end": "10:00",
        "location": "SML — Blackwater Arm", "lat": 37.1801, "lon": -79.6901,
        "weather": "Cloudy", "air": 76, "water": 79,
        "bait": "Umbrella Rig", "style": "Trolling", "anglers": 2,
        "notes": "Tried three different spots. Fish just weren't cooperating.",
        "dwr": 0, "fish": [],
        "spots": [(37.1801, -79.6901), (37.1815, -79.6884)],
    },
    {
        "date": "2026-06-20", "start": "05:00", "end": "09:30",
        "location": "SML — Hales Ford Bridge", "lat": 37.1529, "lon": -79.7149,
        "weather": "Partly Cloudy", "air": 80, "water": 80,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Hit the thermocline at 35 feet. Nice fish in there.",
        "dwr": 1,
        "fish": [
            ("Striper", 27.0, 10.5, True,  35.0),
            ("Striper", 20.0, 5.0,  False, 34.0),
            ("Striper", 18.5, 3.5,  False, 33.0),
        ],
        "spots": [(37.1529, -79.7149)],
    },
    {
        "date": "2026-06-27", "start": "04:45", "end": "08:30",
        "location": "SML — Main Channel", "lat": 37.1649, "lon": -79.7085,
        "weather": "Sunny", "air": 82, "water": 78,
        "bait": "Live Shad", "style": "Planer Boards", "anglers": 3,
        "notes": "Crushed them on boards in the pre-dawn. Limit by 7 AM. Water temp perfect.",
        "dwr": 1,
        "fish": [
            ("Striper", 25.0, 8.5,  True,  None),
            ("Striper", 28.0, 11.0, True,  None),
            ("Striper", 24.0, 7.5,  True,  None),
            ("Striper", 31.0, 15.0, True,  None),
            ("Striper", 22.0, 6.0,  False, None),
            ("Striper", 19.5, 4.5,  False, None),
            ("Striper", 20.0, 5.0,  False, None),
        ],
        "spots": [(37.1649, -79.7085), (37.1657, -79.7068), (37.1664, -79.7052)],
    },
    # ---- July ----
    {
        "date": "2026-07-04", "start": "05:00", "end": "09:00",
        "location": "SML — Roanoke Arm", "lat": 37.1395, "lon": -79.7353,
        "weather": "Sunny", "air": 84, "water": 81,
        "bait": "Live Shad", "style": "Light Lines", "anglers": 2,
        "notes": "Holiday morning. Light winds, good visibility. Fish were down deep.",
        "dwr": 1,
        "fish": [
            ("Striper", 20.5, 5.0, False, 38.0),
            ("Striper", 23.0, 6.5, True,  40.0),
        ],
        "spots": [(37.1395, -79.7353), (37.1381, -79.7371)],
    },
    {
        "date": "2026-07-11", "start": "05:00", "end": "08:30",
        "location": "SML — Main Channel", "lat": 37.1644, "lon": -79.7096,
        "weather": "Partly Cloudy", "air": 81, "water": 82,
        "bait": "Live Shad", "style": "Downlines", "anglers": 2,
        "notes": "Down 40 feet to find them. Short window before the heat killed the bite.",
        "dwr": 1,
        "fish": [
            ("Striper", 24.0, 7.5, True,  40.0),
            ("Striper", 22.0, 6.0, False, 38.0),
            ("Striper", 19.0, 4.0, False, 36.0),
            ("Striper", 21.0, 5.5, False, 40.0),
        ],
        "spots": [(37.1644, -79.7096), (37.1651, -79.7081)],
    },
]

# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------
from fishing_log.database import SESSION_FIELDS


def insert_demo_session(conn, sess: dict) -> int:
    moon = moon_phase_name(sess["date"])
    start = sess.get("start")
    end   = sess.get("end")
    hours = None
    if start and end:
        from datetime import datetime as _dt
        s = _dt.strptime(start, "%H:%M")
        e = _dt.strptime(end,   "%H:%M")
        delta = (e - s).total_seconds() / 3600
        if delta < 0:
            delta += 24
        hours = round(delta, 2)

    params = {
        "user_email":    DEMO_EMAIL,
        "date":          sess["date"],
        "start_time":    start,
        "end_time":      end,
        "hours_fished":  hours,
        "location_name": sess["location"],
        "latitude":      sess["lat"],
        "longitude":     sess["lon"],
        "weather":       sess["weather"],
        "air_temp":      sess["air"],
        "water_temp":    sess["water"],
        "bait_lure":     sess["bait"],
        "fishing_style": sess["style"],
        "num_anglers":   sess["anglers"],
        "dwr_filed":     sess["dwr"],
        "notes":         sess.get("notes", ""),
        "moon_phase":    moon,
    }
    fields = ("user_email",) + SESSION_FIELDS
    cols   = ", ".join(fields)
    placeholders = ", ".join(f":{f}" for f in fields)
    row = conn.execute(
        text(f"INSERT INTO sessions ({cols}) VALUES ({placeholders}) RETURNING id"),
        params,
    )
    return int(row.scalar())


with engine.begin() as conn:
    for i, trip in enumerate(TRIPS, 1):
        sid = insert_demo_session(conn, trip)

        fish_rows = [
            {"species": sp, "length": ln, "weight": wt,
             "kept": kp, "depth": dp}
            for sp, ln, wt, kp, dp in trip["fish"]
        ]
        if fish_rows:
            conn.execute(
                text(
                    "INSERT INTO fish (session_id, species, length, weight, kept, depth) "
                    "VALUES (:session_id, :species, :length, :weight, :kept, :depth)"
                ),
                [
                    {
                        "session_id": sid,
                        "species": f["species"],
                        "length":  float(f["length"]),
                        "weight":  float(f["weight"]),
                        "kept":    int(bool(f["kept"])),
                        "depth":   float(f["depth"]) if f["depth"] else None,
                    }
                    for f in fish_rows
                ],
            )

        spot_rows = [
            {"session_id": sid, "latitude": lat, "longitude": lon,
             "label": None, "caught": 0}
            for lat, lon in trip["spots"]
        ]
        if spot_rows:
            conn.execute(
                text(
                    "INSERT INTO spots (session_id, latitude, longitude, label, caught) "
                    "VALUES (:session_id, :latitude, :longitude, :label, :caught)"
                ),
                spot_rows,
            )

        n_fish = len(trip["fish"])
        label = f"{n_fish} fish" if n_fish else "skunked"
        print(f"  [{i:02d}] {trip['date']} — {trip['location']} — {label}")

print(f"\nDone — 15 demo sessions seeded for {DEMO_EMAIL}")
