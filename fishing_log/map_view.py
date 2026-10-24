"""Build an interactive Folium map of fishing locations, color-coded by success.

Marker color encodes how productive each session was, by total fish landed:
    Skunked (0)   -> black
    Good (1-3)    -> red
    Great (4-6)   -> yellow
    Blowout (7+)  -> blue

Note: rendering the map *basemap* needs internet for the tile layer, but all
underlying data lives locally in SQLite.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import folium
import pandas as pd
from folium.plugins import AntPath, HeatMap

# Success tiers: (inclusive upper bound, label, color). None = no upper bound.
# First matching tier wins, evaluated low -> high.
SUCCESS_TIERS = [
    (0, "Skunked", "#000000"),     # 0 fish   -> black
    (3, "Good", "#e41a1c"),        # 1-3 fish -> red
    (6, "Great", "#f5c518"),       # 4-6 fish -> yellow
    (None, "Blowout", "#1f78b4"),  # 7+ fish  -> blue
]

DEFAULT_CENTER = (37.16463, -79.70913)  # Smith Mountain Lake, VA (home spot)
DEFAULT_ZOOM = 12  # zoomed in on the lake, not the whole region


def _tier(total_fish: int) -> Tuple[str, str]:
    """Return (label, color) for a fish count."""
    for upper, label, color in SUCCESS_TIERS:
        if upper is None or total_fish <= upper:
            return label, color
    return SUCCESS_TIERS[-1][1], SUCCESS_TIERS[-1][2]


def _popup_html(row: pd.Series) -> str:
    """Popup body. User-entered text is escaped — it lands in raw Leaflet HTML."""
    from html import escape

    species = row.get("species_list") or "No fish recorded"
    return (
        f"<b>{escape(str(row.get('location_name', 'Unknown')))}</b><br>"
        f"<b>Date:</b> {row.get('date', '')}<br>"
        f"<b>Fish:</b> {int(row.get('total_fish', 0))}<br>"
        f"<b>Species:</b> {escape(str(species))}<br>"
        f"<b>Weather:</b> {escape(str(row.get('weather', '') or 'n/a'))}<br>"
        f"<b>Air/Water:</b> {row.get('air_temp', 'n/a')}&deg; / {row.get('water_temp', 'n/a')}&deg;<br>"
        f"<b>Bait/Lure:</b> {escape(str(row.get('bait_lure', '') or 'n/a'))}"
    )


def build_map(df: pd.DataFrame) -> folium.Map:
    """Return a Folium map with a marker for each session that has coordinates."""
    plotted = df.dropna(subset=["latitude", "longitude"]) if not df.empty else df

    if plotted.empty:
        return folium.Map(location=DEFAULT_CENTER, zoom_start=DEFAULT_ZOOM)

    center = (plotted["latitude"].mean(), plotted["longitude"].mean())
    fmap = folium.Map(location=center, zoom_start=DEFAULT_ZOOM)

    for _, row in plotted.iterrows():
        n = int(row.get("total_fish", 0))
        label, color = _tier(n)
        # Hover shows date, time, fish count and tier so you know which trip to
        # look up. CircleMarker is Leaflet-drawn (no image), color = catch tier.
        start = row.get("start_time") or ""
        end = row.get("end_time") or ""
        timespan = f" {start}–{end}" if (start or end) else ""
        tooltip = f"{row.get('date', '')}{timespan} · {n} fish ({label})"
        folium.CircleMarker(
            location=(row["latitude"], row["longitude"]),
            radius=9, color="#333333", weight=1.5,  # dark edge keeps all colors visible
            fill=True, fill_color=color, fill_opacity=0.9,
            popup=folium.Popup(_popup_html(row), max_width=300),
            tooltip=tooltip,
        ).add_to(fmap)

    _add_legend(fmap)
    return fmap


# Trolling runs are told apart by line pattern AND marker label ("2·3"), never
# by color alone (color-blind user). Colors are Okabe-Ito; run 1 keeps the
# original blue so a single-run trip looks exactly as it always has.
RUN_STYLES = [
    ("#1f78b4", [10, 20]),
    ("#E69F00", [3, 10]),
    ("#009E73", [18, 8]),
    ("#CC79A7", [6, 6]),
    ("#56B4E9", [14, 4, 2, 4]),
    ("#D55E00", [2, 6]),
]
SPOT_COLOR = "#F0E442"  # single spots: yellow SQUARE marker, labelled S1, S2...


def run_style(run: int) -> tuple:
    """(color, dash pattern) for trolling run ``run`` (1-based), cycling."""
    return RUN_STYLES[(max(1, int(run)) - 1) % len(RUN_STYLES)]


def pin_label(point: dict, runs_on_trip: int, spot_number: int | None = None,
              order_in_run: int | None = None) -> str:
    """Marker text: "3" on a one-run trip, "2·3" with several runs, "S1" for a spot."""
    if point.get("kind") == "spot":
        return f"S{spot_number}"
    return f"{point.get('run') or 1}\u00b7{order_in_run}" if runs_on_trip > 1 \
        else str(order_in_run)


def label_points(points) -> list:
    """Each point with its marker label and a plain-words name, in input order.

    Returns [(point, label, name), ...] where name is e.g. "Run 2, pin 3" or
    "Spot 1". Shared by the maps and the per-pin fish count boxes so the two
    always agree.
    """
    runs = {int(p.get("run") or 1) for p in points if p.get("kind") != "spot"}
    order: dict = {}
    n_spot = 0
    out = []
    for p in points:
        if p.get("kind") == "spot":
            n_spot += 1
            out.append((p, pin_label(p, len(runs), spot_number=n_spot), f"Spot {n_spot}"))
        else:
            r = int(p.get("run") or 1)
            order[r] = order.get(r, 0) + 1
            name = (f"Run {r}, pin {order[r]}" if len(runs) > 1 else f"Pin {order[r]}")
            out.append((p, pin_label(p, len(runs), order_in_run=order[r]), name))
    return out


def _spot_divicon(label, caught: bool, fish_count=None, color: str = "#1f78b4",
                  square: bool = False) -> folium.DivIcon:
    """Route marker. Every pin shows its label (order number, "run·order", or
    "S1" for a single spot); pins where a fish was caught show a fish picture
    with the label as a small corner badge. When two or more fish were caught
    there, a gold ×N badge (bottom corner) shows the count — text-based on
    purpose, never color alone (CB-safe). Single spots are SQUARE, run pins
    round, so shape also tells them apart."""
    label = str(label)
    radius = "3px" if square else "50%" if len(label) <= 2 else "10px"
    if caught:
        count_badge = ""
        if fish_count and int(fish_count) >= 2:
            count_badge = (
                f'<div style="position:absolute;bottom:-4px;right:-6px;background:#f0e442;'
                'border:1px solid #333;border-radius:8px;min-width:18px;height:14px;'
                'padding:0 2px;line-height:13px;font-size:9px;font-weight:bold;'
                f'color:#000;">&times;{int(fish_count)}</div>'
            )
        badge_w = max(16, 6 * len(label) + 6)
        html = (
            '<div style="position:relative;width:30px;height:30px;text-align:center;">'
            '<div style="font-size:24px;line-height:30px;'
            'filter:drop-shadow(0 0 2px #fff) drop-shadow(0 0 2px #fff);">\U0001F41F</div>'
            f'<div style="position:absolute;top:-3px;right:-4px;background:{color};'
            f'border:1px solid #333;border-radius:{"3px" if square else "8px"};'
            f'min-width:{badge_w}px;height:16px;padding:0 2px;box-sizing:border-box;'
            f'line-height:15px;font-size:10px;font-weight:bold;color:#000;">{label}</div>'
            f'{count_badge}'
            '</div>'
        )
        return folium.DivIcon(html=html, icon_size=(30, 30), icon_anchor=(15, 15))
    w = max(24, 8 * len(label) + 8)
    html = (
        f'<div style="background:{color};border:2px solid #333333;border-radius:{radius};'
        f'width:{w}px;height:24px;line-height:21px;text-align:center;box-sizing:border-box;'
        f'font-size:12px;font-weight:bold;color:#000;">{label}</div>'
    )
    return folium.DivIcon(html=html, icon_size=(w, 24), icon_anchor=(w // 2, 12))


def draw_route(fmap: folium.Map, points) -> None:
    """Draw a trip's trolling runs and single spots on a map.

    ``points`` is an ordered list of {lat, lon, caught, fish_count?, kind?,
    run?}. Pins of the same run are joined in order by a moving AntPath that
    shows direction of travel; different runs are NEVER joined to each other
    (packing up and running across the lake is not part of a troll). Single
    spots (kind "spot") get a square marker and no line. A point with no
    kind/run is run 1, so trips from before runs existed draw as they always
    did. 🐟 marks pins where a fish was caught, with a gold ×N badge for 2+.
    """
    runs: dict = {}
    for p in points:
        if p.get("kind") != "spot":
            runs.setdefault(int(p.get("run") or 1), []).append((p["lat"], p["lon"]))
    for run, coords in runs.items():
        if len(coords) >= 2:
            color, dash = run_style(run)
            AntPath(coords, color=color, weight=4, delay=1000,
                    dash_array=dash).add_to(fmap)

    for p, label, name in label_points(points):
        caught = bool(p.get("caught"))
        fc = p.get("fish_count")
        if caught:
            tip = f"{name} · \U0001F3A3 {int(fc)} fish caught" if fc \
                else f"{name} · \U0001F3A3 fish caught"
        else:
            tip = name
        is_spot = p.get("kind") == "spot"
        color = SPOT_COLOR if is_spot else run_style(int(p.get("run") or 1))[0]
        folium.Marker(
            (p["lat"], p["lon"]),
            icon=_spot_divicon(label, caught, fc, color=color, square=is_spot),
            tooltip=tip,
        ).add_to(fmap)


def add_heatmap(fmap: folium.Map, points) -> None:
    """Overlay a catch-hotspot heat layer (points = list of [lat, lon])."""
    if points:
        HeatMap(points, radius=22, blur=18, min_opacity=0.35).add_to(fmap)


def build_route_map(points) -> folium.Map:
    """A standalone map of one session's trolling runs and spots."""
    if not points:
        return folium.Map(location=DEFAULT_CENTER, zoom_start=DEFAULT_ZOOM)
    center = (points[0]["lat"], points[0]["lon"])
    fmap = folium.Map(location=center, zoom_start=DEFAULT_ZOOM + 2)
    draw_route(fmap, points)
    return fmap


def _add_legend(fmap: folium.Map) -> None:
    legend = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
        background: white; padding: 10px 14px; border: 1px solid #999;
        border-radius: 6px; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,.3);">
      <b>Catch success</b><br>
      <span style="color:#000000;">&#9679;</span> Skunked (0)<br>
      <span style="color:#e41a1c;">&#9679;</span> Good (1&ndash;3)<br>
      <span style="color:#f5c518;">&#9679;</span> Great (4&ndash;6)<br>
      <span style="color:#1f78b4;">&#9679;</span> Blowout (7+)
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))


def save_map(df: pd.DataFrame, path: str | Path) -> Path:
    """Build the map and write it to a standalone HTML file. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    build_map(df).save(str(path))
    return path
