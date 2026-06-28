"""Build a pre-filled Google Form link for the Virginia DWR "Striped Bass
Angler Journal" (submits to Dan Wilson).

The form is filled per outing. We pre-populate everything except the email
(the form collects that from the signed-in Google account), so the angler just
opens the link, reviews, and clicks Submit.

Field entry IDs were read from the form's published page.
"""
from __future__ import annotations

from urllib.parse import urlencode

FORM_ID = "1FAIpQLSekzYX_B7oYeGOCO72Gv5LjjaBMctgxGRIlJazqwXPRrJweyg"
FORM_BASE = f"https://docs.google.com/forms/d/e/{FORM_ID}/viewform"

ENTRY = {
    "date": "210458085",        # date question (uses _year/_month/_day for prefill)
    "anglers": "841781509",
    "hours": "1254220858",
    "harvested_n": "1950519841",
    "harvested_sizes": "393064031",
    "released_n": "19977333",
    "released_sizes": "990329712",
}

SPECIES = "Striper"
UNIT = '"'  # inch symbol — keeps the sizes list compact in the form field
# The form collects the responder's email as a normal question; its prefill key
# is the special "emailAddress" param (not an entry.* id).
ANGLER_EMAIL = "jcal0064@gmail.com"


def _fmt_num(value) -> str:
    """Trim trailing .0 so 31.0 -> '31' and 24.5 stays '24.5'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(f)) if f == int(f) else str(f)


def _sizes(rows) -> str:
    """Comma-separated lengths with the inch symbol on each, e.g. '31", 28"'."""
    vals = [_fmt_num(f.get("length")) for f in rows if f.get("length")]
    return ", ".join(f"{v}{UNIT}" for v in vals if v)


def summarize(session: dict) -> dict:
    """Compute the DWR report values for one session (stripers only)."""
    stripers = [
        f for f in session.get("fish", [])
        if (f.get("species") or "").strip().lower() == SPECIES.lower()
    ]
    kept = [f for f in stripers if f.get("kept")]
    released = [f for f in stripers if not f.get("kept")]
    harvested_n, released_n = len(kept), len(released)

    return {
        "date": session.get("date", ""),
        "anglers": int(session.get("num_anglers") or 1),
        "hours": _fmt_num(session.get("hours_fished")),
        "harvested_n": harvested_n,
        # Always N/A when none harvested; otherwise the recorded sizes (you can
        # fill/adjust on the form for the rare harvest).
        "harvested_sizes": "N/A" if harvested_n == 0 else _sizes(kept),
        "released_n": released_n,
        "released_sizes": "N/A" if released_n == 0 else _sizes(released),
    }


def prefilled_url(session: dict, email: str = ANGLER_EMAIL) -> str:
    """Return a pre-filled Google Form URL for this session's striper report."""
    r = summarize(session)
    params = [
        ("emailAddress", email),
        (f"entry.{ENTRY['anglers']}", r["anglers"]),
        (f"entry.{ENTRY['hours']}", r["hours"]),
        (f"entry.{ENTRY['harvested_n']}", r["harvested_n"]),
        (f"entry.{ENTRY['harvested_sizes']}", r["harvested_sizes"]),
        (f"entry.{ENTRY['released_n']}", r["released_n"]),
        (f"entry.{ENTRY['released_sizes']}", r["released_sizes"]),
    ]
    # Date question prefill takes separate year/month/day params.
    date = str(r["date"])[:10]
    if date.count("-") == 2:
        y, m, d = date.split("-")
        params += [
            (f"entry.{ENTRY['date']}_year", y),
            (f"entry.{ENTRY['date']}_month", str(int(m))),
            (f"entry.{ENTRY['date']}_day", str(int(d))),
        ]
    return f"{FORM_BASE}?usp=pp_url&{urlencode(params)}"
