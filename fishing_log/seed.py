"""Sample data so the app is immediately explorable on first run.

~18 sessions across several real lakes/rivers, multiple seasons and weather
conditions, with mixed-species catches and a few skunked days. Coordinates are
real so the map renders meaningfully. Idempotent: does nothing if data exists.
"""
from __future__ import annotations

from . import database as db
from . import data_entry

# (session_dict, [catches]) tuples. hours_fished left blank where start/end set,
# so it is auto-computed by data_entry.compute_hours.
_SAMPLES = [
    (
        {"date": "2025-04-12", "start_time": "06:30", "end_time": "11:00",
         "location_name": "Lake Fork", "latitude": 32.8460, "longitude": -95.5460,
         "weather": "Partly Cloudy", "air_temp": 62, "water_temp": 58,
         "bait_lure": "Chatterbait (green pumpkin)", "notes": "Spawn just starting in coves."},
        [{"species": "Largemouth Bass", "count": 7}],
    ),
    (
        {"date": "2025-05-03", "start_time": "05:45", "end_time": "10:30",
         "location_name": "Lake Fork", "latitude": 32.8460, "longitude": -95.5460,
         "weather": "Overcast", "air_temp": 70, "water_temp": 66,
         "bait_lure": "Texas-rigged worm", "notes": "Post-front, tough bite."},
        [{"species": "Largemouth Bass", "count": 2}, {"species": "Crappie", "count": 4}],
    ),
    (
        {"date": "2025-06-21", "start_time": "06:00", "end_time": "12:00",
         "location_name": "Lake Guntersville", "latitude": 34.4000, "longitude": -86.3000,
         "weather": "Sunny", "air_temp": 88, "water_temp": 82,
         "bait_lure": "Topwater frog", "notes": "Heavy grass mats, explosive blowups."},
        [{"species": "Largemouth Bass", "count": 9}],
    ),
    (
        {"date": "2025-07-04", "start_time": "13:00", "end_time": "17:00",
         "location_name": "Lake Guntersville", "latitude": 34.4000, "longitude": -86.3000,
         "weather": "Sunny", "air_temp": 94, "water_temp": 86,
         "bait_lure": "Deep crankbait", "notes": "Midday heat, skunked."},
        [],
    ),
    (
        {"date": "2025-05-18", "start_time": "07:00", "end_time": "13:30",
         "location_name": "Lake of the Woods", "latitude": 49.2700, "longitude": -94.8700,
         "weather": "Cloudy", "air_temp": 55, "water_temp": 52,
         "bait_lure": "Jig & minnow", "notes": "Classic walleye trolling."},
        [{"species": "Walleye", "count": 12}, {"species": "Northern Pike", "count": 3}],
    ),
    (
        {"date": "2025-08-09", "start_time": "06:15", "end_time": "11:45",
         "location_name": "Lake of the Woods", "latitude": 49.2700, "longitude": -94.8700,
         "weather": "Windy", "air_temp": 72, "water_temp": 70,
         "bait_lure": "Crawler harness", "notes": "Big wind, drifted mud line."},
        [{"species": "Walleye", "count": 6}, {"species": "Sauger", "count": 2}],
    ),
    (
        {"date": "2025-09-14", "start_time": "08:00", "end_time": "14:00",
         "location_name": "Bighorn River", "latitude": 45.5000, "longitude": -107.9500,
         "weather": "Partly Cloudy", "air_temp": 64, "water_temp": 54,
         "bait_lure": "BWO dry fly", "notes": "Fall blue-wing hatch, great day."},
        [{"species": "Brown Trout", "count": 8}, {"species": "Rainbow Trout", "count": 5}],
    ),
    (
        {"date": "2025-10-05", "start_time": "09:00", "end_time": "15:00",
         "location_name": "Bighorn River", "latitude": 45.5000, "longitude": -107.9500,
         "weather": "Rain", "air_temp": 48, "water_temp": 50,
         "bait_lure": "Streamer (sculpin)", "notes": "Cold rain, only a couple browns."},
        [{"species": "Brown Trout", "count": 2}],
    ),
    (
        {"date": "2025-06-07", "start_time": "06:00", "end_time": "12:30",
         "location_name": "Lake Erie", "latitude": 41.7000, "longitude": -82.5000,
         "weather": "Sunny", "air_temp": 76, "water_temp": 68,
         "bait_lure": "Worm harness (chartreuse)", "notes": "Western basin walleye, limit out."},
        [{"species": "Walleye", "count": 18}, {"species": "Yellow Perch", "count": 10}],
    ),
    (
        {"date": "2025-09-20", "start_time": "07:30", "end_time": "12:00",
         "location_name": "Lake Erie", "latitude": 41.7000, "longitude": -82.5000,
         "weather": "Overcast", "air_temp": 60, "water_temp": 64,
         "bait_lure": "Perch rig (emerald shiner)", "notes": "Jumbo perch on the reefs."},
        [{"species": "Yellow Perch", "count": 25}],
    ),
    (
        {"date": "2025-03-22", "start_time": "10:00", "end_time": "16:00",
         "location_name": "Lake Okeechobee", "latitude": 26.9500, "longitude": -80.8300,
         "weather": "Sunny", "air_temp": 80, "water_temp": 72,
         "bait_lure": "Wild shiners", "notes": "Sight-fishing bedding bass."},
        [{"species": "Largemouth Bass", "count": 6}, {"species": "Bluegill", "count": 8}],
    ),
    (
        {"date": "2025-11-15", "start_time": "07:00", "end_time": "11:00",
         "location_name": "Lake Okeechobee", "latitude": 26.9500, "longitude": -80.8300,
         "weather": "Fog", "air_temp": 66, "water_temp": 68,
         "bait_lure": "Speck jig", "notes": "Crappie (specks) schooling in open water."},
        [{"species": "Crappie", "count": 22}],
    ),
    (
        {"date": "2025-07-19", "start_time": "05:00", "end_time": "10:00",
         "location_name": "Kenai River", "latitude": 60.5000, "longitude": -150.9000,
         "weather": "Cloudy", "air_temp": 58, "water_temp": 48,
         "bait_lure": "Salmon roe / bead", "notes": "Sockeye run, flossing the slot."},
        [{"species": "Sockeye Salmon", "count": 4}],
    ),
    (
        {"date": "2025-08-23", "start_time": "06:00", "end_time": "14:00",
         "location_name": "Kenai River", "latitude": 60.5000, "longitude": -150.9000,
         "weather": "Rain", "air_temp": 54, "water_temp": 46,
         "bait_lure": "Spin-n-glo", "notes": "Late silvers, slow but quality fish."},
        [{"species": "Coho Salmon", "count": 3}, {"species": "Dolly Varden", "count": 5}],
    ),
    (
        {"date": "2025-05-30", "start_time": "06:30", "end_time": "12:00",
         "location_name": "Lake Champlain", "latitude": 44.5000, "longitude": -73.3000,
         "weather": "Partly Cloudy", "air_temp": 68, "water_temp": 60,
         "bait_lure": "Drop shot (goby imitation)", "notes": "Smallmouth on rocky humps."},
        [{"species": "Smallmouth Bass", "count": 11}],
    ),
    (
        {"date": "2025-10-18", "start_time": "08:30", "end_time": "13:30",
         "location_name": "Lake Champlain", "latitude": 44.5000, "longitude": -73.3000,
         "weather": "Windy", "air_temp": 50, "water_temp": 54,
         "bait_lure": "Jerkbait", "notes": "Cold front blew through, nothing."},
        [],
    ),
    (
        {"date": "2025-04-26", "start_time": "06:00", "end_time": "11:30",
         "location_name": "Falcon Lake", "latitude": 26.7000, "longitude": -99.2000,
         "weather": "Sunny", "air_temp": 84, "water_temp": 74,
         "bait_lure": "Carolina rig (lizard)", "notes": "Big Texas bass on main-lake points."},
        [{"species": "Largemouth Bass", "count": 5}],
    ),
    (
        {"date": "2025-12-28", "start_time": "09:00", "end_time": "13:00",
         "location_name": "San Diego Bay", "latitude": 32.7000, "longitude": -117.2000,
         "weather": "Partly Cloudy", "air_temp": 63, "water_temp": 59,
         "bait_lure": "Sabiki + live bait", "notes": "Winter bay bass and bonito."},
        [{"species": "Spotted Bay Bass", "count": 9}, {"species": "Bonito", "count": 2}],
    ),
]


def seed_sample_data(force: bool = False) -> int:
    """Insert sample sessions. Returns the number of sessions added.

    Skips insertion if the database already has sessions, unless ``force``.
    """
    db.init_db()
    if not force and db.session_count() > 0:
        return 0
    added = 0
    for session, catches in _SAMPLES:
        data_entry.add_session(session, catches)
        added += 1
    return added


if __name__ == "__main__":
    n = seed_sample_data()
    print(f"Seeded {n} sample sessions into {db.get_db_path()}")
