"""Turn a GTFS static feed into map overlays (design section 3.4).

Streams the zip so the 400 MB `stop_times.txt` is never read: routes, shapes,
trips and stops are enough to draw lines and stops.
"""

import csv
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import date

RAIL_TYPES = {"0", "1", "2"}  # tram, subway/metro, rail
MAX_SHAPES_PER_ROUTE = 4
MIN_SHAPE_SHARE = 0.25  # keep branches carrying at least this share of trips
MIN_STEP_M = 15.0  # thin shape points closer together than this


def _rows(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def _meters(a, b) -> float:
    """Approximate distance in metres between two (lon, lat) points."""
    dx = math.radians(b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = math.radians(b[1] - a[1])
    return 6371000.0 * math.hypot(dx, dy)


def thin(points: list[tuple[float, float]]) -> list[list[float]]:
    out = [points[0]]
    for point in points[1:-1]:
        if _meters(out[-1], point) >= MIN_STEP_M:
            out.append(point)
    if len(points) > 1:
        out.append(points[-1])
    return [[round(x, 5), round(y, 5)] for x, y in out]


def parse(zf: zipfile.ZipFile) -> dict:
    """Return {"rail", "bus", "stops", "meta"}: GeoJSON collections and facts."""
    routes = {r["route_id"]: r for r in _rows(zf, "routes.txt")}

    shape_trips: dict[str, Counter] = defaultdict(Counter)
    for trip in _rows(zf, "trips.txt"):
        if trip.get("shape_id") and trip["route_id"] in routes:
            shape_trips[trip["route_id"]][trip["shape_id"]] += 1

    keep: dict[str, str] = {}  # shape_id -> route_id
    for route_id, counts in shape_trips.items():
        top = counts.most_common(1)[0][1]
        chosen = [s for s, n in counts.most_common(MAX_SHAPES_PER_ROUTE) if n >= top * MIN_SHAPE_SHARE]
        for shape_id in chosen:
            keep[shape_id] = route_id

    raw_shapes: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for row in _rows(zf, "shapes.txt"):
        if row["shape_id"] in keep:
            raw_shapes[row["shape_id"]].append(
                (int(row["shape_pt_sequence"]), float(row["shape_pt_lon"]), float(row["shape_pt_lat"]))
            )

    rail, bus = [], []
    for shape_id, pts in raw_shapes.items():
        pts.sort()
        coords = thin([(x, y) for _, x, y in pts])
        if len(coords) < 2:
            continue
        route = routes[keep[shape_id]]
        color = (route.get("route_color") or "666666").lstrip("#").upper()
        feature = {
            "type": "Feature",
            "properties": {
                "route": route["route_id"],
                "name": route.get("route_long_name") or route.get("route_short_name", ""),
                "short": route.get("route_short_name", ""),
                "color": "#" + color,
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        }
        (rail if route["route_type"] in RAIL_TYPES else bus).append(feature)

    stops = []
    for stop in _rows(zf, "stops.txt"):
        if stop.get("parent_station"):
            continue  # a platform of a station already listed
        try:
            lon, lat = float(stop["stop_lon"]), float(stop["stop_lat"])
        except (KeyError, ValueError):
            continue
        stops.append({
            "type": "Feature",
            "properties": {
                "id": stop["stop_id"],
                "name": stop.get("stop_name", ""),
                "kind": "rail" if stop.get("location_type") == "1" else "bus",
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        })

    return {
        "rail": {"type": "FeatureCollection", "features": rail},
        "bus": {"type": "FeatureCollection", "features": bus},
        "stops": {"type": "FeatureCollection", "features": stops},
        "meta": {"valid_to": _valid_to(zf), "routes": len(routes)},
    }


def _valid_to(zf: zipfile.ZipFile) -> str | None:
    """The last service date in the feed, as ISO text (design: expiry banner)."""
    ends = []
    for name in ("calendar.txt", "calendar_dates.txt"):
        if name in zf.namelist():
            col = "end_date" if name == "calendar.txt" else "date"
            ends += [r[col] for r in _rows(zf, name) if r.get(col)]
    if not ends:
        return None
    last = max(ends)
    return date(int(last[:4]), int(last[4:6]), int(last[6:8])).isoformat()


def write(zip_path, out_dir) -> dict:
    """Parse the zip and write rail/bus/stops GeoJSON into out_dir."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        parsed = parse(zf)
    for name in ("rail", "bus", "stops"):
        tmp = out / f".{name}.geojson.tmp"
        tmp.write_text(json.dumps(parsed[name], separators=(",", ":")), encoding="utf-8")
        tmp.replace(out / f"{name}.geojson")
    parsed["meta"]["counts"] = {n: len(parsed[n]["features"]) for n in ("rail", "bus", "stops")}
    return parsed["meta"]
