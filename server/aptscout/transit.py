"""The simple CTA travel time model (design section 4.3).

Walk to the nearest useful stop, wait half a headway, ride a distance
estimated from the straight line at an average speed, walk from the stop. It
does not know which lines connect which stops, so it can be wrong where a trip
needs a transfer; schedule-based routing (M5) replaces it. The result is
labelled `estimate` everywhere.
"""

import sqlite3

from . import routing

RAIL_KMH = 30.0
BUS_KMH = 15.0
RIDE_DETOUR = {"rail": 1.2, "bus": 1.3}
TRANSFER_MIN = 6.0  # added to every ride: one transfer on average
MAX_ACCESS_M = 1600.0  # a stop farther than this is not "walk to the stop"
# Typical headways in minutes by time band: (rail, bus). Half is the average wait.
HEADWAYS = {
    "weekday_rush": (5.0, 8.0),
    "weekday_midday": (8.0, 12.0),
    "evening": (12.0, 15.0),
    "saturday": (10.0, 15.0),
    "sunday": (12.0, 18.0),
}
BANDS = tuple(HEADWAYS)
KIND_CATEGORY = {"rail": "rail_station", "bus": "bus_stop"}
CELL = 0.02  # degrees, about 2.2 km: wider than MAX_ACCESS_M, so 3 x 3 cells cover a search
_GRIDS: dict[tuple, dict[tuple[int, int], list[tuple[float, float]]]] = {}


def _cell(point: tuple[float, float]) -> tuple[int, int]:
    return int(point[0] // CELL), int(point[1] // CELL)


def stops(conn: sqlite3.Connection, kind: str) -> dict[tuple[int, int], list[tuple[float, float]]]:
    """The CTA stops of one kind on a grid; rebuilt when the stop list changes."""
    count = conn.execute("SELECT count(*), max(id) FROM place WHERE category_key = ? AND gone = 0",
                         (KIND_CATEGORY[kind],)).fetchone()
    key = (conn.execute("PRAGMA database_list").fetchone()[2], kind, tuple(count))
    if key not in _GRIDS:
        grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for lat, lon in conn.execute("SELECT lat, lon FROM place WHERE category_key = ? AND gone = 0",
                                     (KIND_CATEGORY[kind],)):
            grid.setdefault(_cell((lat, lon)), []).append((lat, lon))
        for old in [k for k in _GRIDS if k[:2] == key[:2]]:
            del _GRIDS[old]  # the same database and kind with a different stop list
        _GRIDS[key] = grid
    return _GRIDS[key]


def nearest(point: routing.Point, grid) -> tuple[tuple[float, float], float] | None:
    cy, cx = _cell(point)
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in grid.get((cy + dy, cx + dx), ()):
                d = routing.haversine_m(point, c)
                if best is None or d < best[1]:
                    best = (c, d)
    return best if best and best[1] <= MAX_ACCESS_M else None


def estimate(conn: sqlite3.Connection, origin: routing.Point, dest: routing.Point, band: str) -> tuple[float, str]:
    """Minutes and the method used ('walk', 'rail' or 'bus') for the cheapest option."""
    walk_all = routing.walk_minutes(routing.haversine_m(origin, dest) * routing.DETOUR)
    best = (walk_all, "walk")
    rail_headway, bus_headway = HEADWAYS[band]
    for kind, headway, speed in (("rail", rail_headway, RAIL_KMH), ("bus", bus_headway, BUS_KMH)):
        a = nearest(origin, stops(conn, kind))
        b = nearest(dest, stops(conn, kind))
        if a is None or b is None or a[0] == b[0]:
            continue
        ride_m = routing.haversine_m(a[0], b[0]) * RIDE_DETOUR[kind]
        total = (routing.walk_minutes(a[1] * routing.DETOUR) + headway / 2 + ride_m / (speed * 1000 / 60)
                 + TRANSFER_MIN + routing.walk_minutes(b[1] * routing.DETOUR))
        if total < best[0]:
            best = (total, kind)
    return best
