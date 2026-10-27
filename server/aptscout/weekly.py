"""Weekly travel time (design section 5).

For each destination: the trips per week times the round trip in the chosen
mode, from an apartment. A destination is a point (the job) or a category (the
best grocery store). One-way times are cached per apartment, destination,
place, band and data version.
"""

import sqlite3

import httpx

from . import datasets, otp as otp_module, routing, transit

SELECTION_RULES = ("best", "nearest", "favourite", "mean_n")
MODES = ("walk", "bike", "drive", "transit")
BANDS = transit.BANDS
PREFILTER = 10
DRIVE_RUSH_MULTIPLIER = 1.3  # free-flow speeds; rush hour slows the drive down


def data_version(router: routing.Router, otp=None) -> str:
    """Routers, the CTA feed's fetch time and the OTP graph's build: a new feed or graph makes cached times stale."""
    versions = datasets.read_versions()
    cta = versions.get("cta_gtfs", {}).get("fetched_at", "none")
    graph = versions.get("otp_inputs", {}).get("fetched_at", "none") if otp else "-"
    return f"{router.name}/{'otp' if otp else 'estimate'}/{cta}/{graph}"


def one_way(conn: sqlite3.Connection, router: routing.Router, origin: routing.Point, target: routing.Point,
            mode: str, band: str, direction: str = "out", otp=None) -> tuple[float, str]:
    """Minutes and method for one direction (symmetric geometry; the band shapes waits and traffic)."""
    if mode == "transit":
        if otp is not None:
            try:
                return otp.minutes(origin, target, band, direction)
            except (otp_module.NoRoute, httpx.HTTPError):
                minutes, kind = transit.estimate(conn, origin, target, band)
                return minutes, f"estimate:fallback:{kind}"  # not cached: OTP may come back
        minutes, kind = transit.estimate(conn, origin, target, band)
        return minutes, f"estimate:{kind}"
    minutes = router.travel_minutes(origin, [target], mode)[0]
    if minutes is None:
        raise LookupError("unreachable")
    if mode == "drive" and band == "weekday_rush":
        minutes *= DRIVE_RUSH_MULTIPLIER
    return minutes, "valhalla" if router.name == "valhalla" else "estimate"


def cached_one_way(conn, router, apt_id, dest_id, place_id, direction, origin, target, mode, band, version, otp=None):
    row = conn.execute(
        "SELECT minutes, method FROM travel_time WHERE apartment_id=? AND destination_id=? AND place_id=?"
        " AND direction=? AND mode=? AND band=? AND version=?",
        (apt_id, dest_id, place_id, direction, mode, band, version)).fetchone()
    if row:
        return row["minutes"], row["method"]
    minutes, method = one_way(conn, router, origin, target, mode, band, direction, otp)
    if not method.startswith("estimate:fallback"):
        with conn:
            conn.execute("INSERT OR REPLACE INTO travel_time VALUES (?,?,?,?,?,?,?,?,?)",
                         (apt_id, dest_id, place_id, direction, mode, band, minutes, method, version))
    return minutes, method


def category_targets(conn, owner_id: int, dest: sqlite3.Row, origin: routing.Point) -> list[sqlite3.Row]:
    """Candidate places of the destination's category: nearest by straight line, plus favourites."""
    rows = conn.execute(
        "SELECT p.id, p.name, p.lat, p.lon, COALESCE(m.favourite,0) AS favourite FROM place p"
        " LEFT JOIN place_mark m ON m.owner_id = ? AND m.place_id = p.id"
        " WHERE p.category_key = ? AND p.gone = 0 AND (p.owner_id IS NULL OR p.owner_id = ?)"
        " AND COALESCE(m.hidden,0) = 0"
        + (" AND COALESCE(m.state,'unreviewed') = 'confirmed'" if dest["category_key"] == "lap_pool" else ""),
        (owner_id, dest["category_key"], owner_id)).fetchall()
    rows.sort(key=lambda r: routing.haversine_m(origin, (r["lat"], r["lon"])))
    chosen = {r["id"]: r for r in rows[:PREFILTER]}
    for r in rows:
        if r["favourite"]:
            chosen[r["id"]] = r
    return list(chosen.values())


def destination_time(conn, owner_id: int, router, apt: sqlite3.Row, dest: sqlite3.Row, version: str, otp=None) -> dict:
    origin = (apt["lat"], apt["lon"])
    back_band = dest["return_band"] or dest["time_band"]
    base = {"id": dest["id"], "name": dest["name"], "trips": dest["trips_per_week"], "mode": dest["mode"],
            "band": dest["time_band"], "return_band": back_band, "max_minutes": dest["max_minutes"],
            "place": None, "out": None, "back": None, "round_trip": None, "weekly": None,
            "method": None, "note": "", "over_budget": False}
    if dest["kind"] == "place":
        if dest["lat"] is None:
            return {**base, "note": "no location set"}
        options = [(0, dest["name"], (dest["lat"], dest["lon"]))]
        rule = "best"
    else:
        found = category_targets(conn, owner_id, dest, origin)
        if not found:
            return {**base, "note": "no places in this category"}
        rule = dest["selection_rule"]
        found.sort(key=lambda r: routing.haversine_m(origin, (r["lat"], r["lon"])))
        if rule == "nearest":
            found = found[:1]
        elif rule == "favourite":
            favs = [r for r in found if r["favourite"]]
            found = favs[:1] or found[:1]
            base["note"] = "" if favs else "no favourite set; using the nearest"
        elif rule == "mean_n":
            found = found[:dest["n"]]
        options = [(r["id"], r["name"], (r["lat"], r["lon"])) for r in found]

    results = []
    for place_id, name, target in options:
        out, method = cached_one_way(conn, router, apt["id"], dest["id"], place_id, "out", origin, target,
                                     dest["mode"], dest["time_band"], version, otp)
        back, _ = cached_one_way(conn, router, apt["id"], dest["id"], place_id, "back", target, origin,
                                 dest["mode"], back_band, version, otp)
        results.append((out + back, out, back, place_id, name, target, method))
    if rule == "mean_n":
        round_trip = sum(r[0] for r in results) / len(results)
        out = sum(r[1] for r in results) / len(results)
        back = sum(r[2] for r in results) / len(results)
        pick = min(results)
        base["note"] = f"mean of the nearest {len(results)}"
    else:
        round_trip, out, back, place_id, name, target, method = min(results)
        pick = (round_trip, out, back, place_id, name, target, method)
    _, _, _, place_id, name, target, method = pick
    round_trip = round(round_trip, 1)  # shown figures multiply out exactly
    base.update(place={"id": place_id, "name": name, "lat": target[0], "lon": target[1]},
                out=round(out, 1), back=round(back, 1), round_trip=round_trip,
                weekly=round(round_trip * dest["trips_per_week"], 1), method=method)
    if dest["max_minutes"] is not None and max(out, back) > dest["max_minutes"]:
        base["over_budget"] = True
    return base


def weekly_for_apartment(conn: sqlite3.Connection, owner_id: int, apt: sqlite3.Row, router: routing.Router, otp=None) -> dict:
    """{"total": minutes or None, "complete": bool, "destinations": [...]}."""
    dests = conn.execute("SELECT * FROM destination WHERE owner_id = ? ORDER BY id", (owner_id,)).fetchall()
    if apt["lat"] is None or not dests:
        return {"total": None if apt["lat"] is None else 0.0, "complete": apt["lat"] is not None, "destinations": []}
    version = data_version(router, otp)
    parts = [destination_time(conn, owner_id, router, apt, d, version, otp) for d in dests]
    total = round(sum(p["weekly"] or 0.0 for p in parts), 1)
    return {"total": total, "complete": all(p["weekly"] is not None for p in parts), "destinations": parts}
