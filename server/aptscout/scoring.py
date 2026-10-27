"""Category scores for an apartment (design section 6).

Every category's score is 0 to 100 from the walking minutes to the place(s)
it counts: full marks within `d_good`, none beyond `d_max`, linear between.
The place score is the weighted mean over categories with a weight above 0.
Thresholds are always walking minutes; `measure` only picks how the minutes
are derived (straight line, street network distance, street network time).
"""

import math
import sqlite3

from . import categories, routing

NEAREST_N = 3
PREFILTER = 10  # candidates routed per category (nearest by straight line)


def curve(minutes: float, d_good: float, d_max: float) -> float:
    if minutes <= d_good:
        return 100.0
    if minutes >= d_max or d_max <= d_good:
        return 0.0
    return 100.0 * (d_max - minutes) / (d_max - d_good)


def candidates(conn: sqlite3.Connection, owner_id: int, cat: sqlite3.Row, origin: routing.Point) -> list[sqlite3.Row]:
    """Places the category may count, near the origin, favourites always included."""
    radius_m = cat["d_max"] * routing.WALK_KMH * 1000 / 60
    dlat = radius_m / 111000.0
    dlon = radius_m / (111000.0 * max(math.cos(math.radians(origin[0])), 0.01))
    sql = (
        "SELECT p.id, p.name, p.lat, p.lon, COALESCE(m.favourite,0) AS favourite FROM place p"
        " LEFT JOIN place_mark m ON m.owner_id = ? AND m.place_id = p.id"
        " WHERE p.category_key = ? AND p.gone = 0 AND (p.owner_id IS NULL OR p.owner_id = ?)"
        " AND COALESCE(m.hidden,0) = 0"
    )
    args: list = [owner_id, cat["key"], owner_id]
    if cat["key"] == "lap_pool":
        sql += " AND COALESCE(m.state,'unreviewed') = 'confirmed'"  # candidates count only once confirmed
    rows = conn.execute(sql, args).fetchall()
    near = [r for r in rows
            if abs(r["lat"] - origin[0]) <= dlat and abs(r["lon"] - origin[1]) <= dlon]
    near.sort(key=lambda r: routing.haversine_m(origin, (r["lat"], r["lon"])))
    chosen = {r["id"]: r for r in near[:PREFILTER]}
    for r in rows:
        if r["favourite"]:
            chosen[r["id"]] = r
    return list(chosen.values())


def minutes_to(conn: sqlite3.Connection, apartment_id: int, origin: routing.Point, places: list[sqlite3.Row],
               measure: str, router: routing.Router) -> dict[int, float]:
    """Walking minutes per place id, from the cache or the router (then cached)."""
    key = f"{measure}:{router.name}"
    have = {
        r["place_id"]: r["minutes"]
        for r in conn.execute(
            "SELECT place_id, minutes FROM apartment_distance WHERE apartment_id = ? AND measure = ?",
            (apartment_id, key),
        )
    }
    missing = [p for p in places if p["id"] not in have]
    if missing:
        values = router.walk_minutes(origin, [(p["lat"], p["lon"]) for p in missing], measure)
        with conn:
            for place, value in zip(missing, values):
                if value is not None:
                    have[place["id"]] = value
                    conn.execute(
                        "INSERT OR REPLACE INTO apartment_distance (apartment_id, place_id, measure, minutes)"
                        " VALUES (?,?,?,?)", (apartment_id, place["id"], key, value))
    return {p["id"]: have[p["id"]] for p in places if p["id"] in have}


def score_category(conn, owner_id: int, apartment_id: int, origin: routing.Point, cat: sqlite3.Row,
                   router: routing.Router) -> dict:
    places = candidates(conn, owner_id, cat, origin)
    times = minutes_to(conn, apartment_id, origin, places, cat["measure"], router)
    ranked = sorted((times[p["id"]], p) for p in places if p["id"] in times)
    note = ""
    counted: list[tuple[float, sqlite3.Row]] = ranked
    if cat["aggregation"] == "favourite":
        favs = [(t, p) for t, p in ranked if p["favourite"]]
        if favs:
            counted = favs[:1]
        else:
            note = "no favourite set; using the nearest"
    if not counted:
        return {"key": cat["key"], "name": cat["name"], "weight": cat["weight"], "score": 0.0, "minutes": None,
                "place": None, "note": note or f"none within {cat['d_max']:g} min", "measure": cat["measure"]}
    if cat["aggregation"] == "mean_n":
        top = counted[:NEAREST_N]
        minutes = sum(t for t, _ in top) / len(top)
        note = f"mean of the nearest {len(top)}"
        place = top[0][1]
    else:
        minutes, place = counted[0]
    return {"key": cat["key"], "name": cat["name"], "weight": cat["weight"],
            "score": round(curve(minutes, cat["d_good"], cat["d_max"]), 1), "minutes": round(minutes, 1),
            "place": {"id": place["id"], "name": place["name"], "lat": place["lat"], "lon": place["lon"]},
            "note": note, "measure": cat["measure"]}


def score_apartment(conn: sqlite3.Connection, owner_id: int, apartment: sqlite3.Row, router: routing.Router) -> dict:
    """{"place_score": float | None, "categories": [...]} for an apartment with a pin."""
    if apartment["lat"] is None:
        return {"place_score": None, "categories": [], "note": "no location yet"}
    origin = (apartment["lat"], apartment["lon"])
    cats = conn.execute("SELECT * FROM category WHERE owner_id = ? AND weight > 0 ORDER BY weight DESC, id", (owner_id,)).fetchall()
    rows = [score_category(conn, owner_id, apartment["id"], origin, c, router) for c in cats]
    total = sum(c["weight"] for c in cats)
    for row in rows:
        row["share"] = round(100 * row["weight"] / total, 1) if total else 0.0
        row["contribution"] = round(row["score"] * row["weight"] / total, 1) if total else 0.0
    score = round(sum(r["contribution"] for r in rows), 1) if total else None
    return {"place_score": score, "categories": rows}
