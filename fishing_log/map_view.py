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
    species = row.get("species_list") or "No fish recorded"
    return (
        f"<b>{row.get('location_name', 'Unknown')}</b><br>"
        f"<b>Date:</b> {row.get('date', '')}<br>"
        f"<b>Fish:</b> {int(row.get('total_fish', 0))}<br>"
        f"<b>Species:</b> {species}<br>"
        f"<b>Weather:</b> {row.get('weather', '') or 'n/a'}<br>"
        f"<b>Air/Water:</b> {row.get('air_temp', 'n/a')}&deg; / {row.get('water_temp', 'n/a')}&deg;<br>"
        f"<b>Bait/Lure:</b> {row.get('bait_lure', '') or 'n/a'}"
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


def _spot_divicon(number: int, caught: bool) -> folium.DivIcon:
    """Route marker. Every spot shows its order number; spots where a fish was
    caught show a fish picture with the number as a small corner badge."""
    if caught:
        # Fish picture + numbered badge so order is still readable.
        html = (
            '<div style="position:relative;width:30px;height:30px;text-align:center;">'
            '<div style="font-size:24px;line-height:30px;'
            'filter:drop-shadow(0 0 2px #fff) drop-shadow(0 0 2px #fff);">\U0001F41F</div>'
            f'<div style="position:absolute;top:-3px;right:-4px;background:#1f78b4;'
            'border:1px solid #fff;border-radius:50%;width:16px;height:16px;'
            f'line-height:15px;font-size:10px;font-weight:bold;color:#fff;">{number}</div>'
            '</div>'
        )
        return folium.DivIcon(html=html, icon_size=(30, 30), icon_anchor=(15, 15))
    html = (
        f'<div style="background:#1f78b4;border:2px solid #333333;border-radius:50%;'
        f'width:24px;height:24px;line-height:21px;text-align:center;'
        f'font-size:12px;font-weight:bold;color:#000;">{number}</div>'
    )
    return folium.DivIcon(html=html, icon_size=(24, 24), icon_anchor=(12, 12))


def draw_route(fmap: folium.Map, points) -> None:
    """Draw a numbered, directional trolling route on a map.

    ``points`` is an ordered list of {lat, lon, caught}. A moving AntPath shows
    the direction of travel; numbered markers show order; gold 🎣 markers mark
    spots where a fish was caught.
    """
    coords = [(p["lat"], p["lon"]) for p in points]
    if len(coords) >= 2:
        AntPath(coords, color="#1f78b4", weight=4, delay=1000, dash_array=[10, 20]).add_to(fmap)
    for i, p in enumerate(points, 1):
        caught = bool(p.get("caught"))
        folium.Marker(
            (p["lat"], p["lon"]),
            icon=_spot_divicon(i, caught),
            tooltip=f"Spot {i}" + (" · \U0001F3A3 fish caught" if caught else ""),
        ).add_to(fmap)


def add_heatmap(fmap: folium.Map, points) -> None:
    """Overlay a catch-hotspot heat layer (points = list of [lat, lon])."""
    if points:
        HeatMap(points, radius=22, blur=18, min_opacity=0.35).add_to(fmap)


def build_route_map(points) -> folium.Map:
    """A standalone map of one session's trolling route (numbered + directional)."""
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
