"""Import public places into the database (design sections 3.2 and 3.3).

Imported rows have an `ext_id` and no owner. A re-import updates rows the
owner has not edited, revives rows that returned, and flags rows that vanished
as `gone` instead of deleting them (owner marks and notes stay attached).
"""

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import categories, config

MERGE_RADIUS_M = 100.0


@dataclass
class Imported:
    ext_id: str
    category: str
    name: str
    lat: float
    lon: float
    source: str
    address: str = ""
    lap_score: str | None = None
    also: str = ""


@dataclass
class Stats:
    added: int = 0
    updated: int = 0
    kept_edited: int = 0
    gone: int = 0
    revived: int = 0
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"added {self.added}, updated {self.updated}, kept {self.kept_edited} edited, "
                f"revived {self.revived}, gone {self.gone}")


def metres_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    dy = math.radians(lat2 - lat1)
    return 6371000.0 * math.hypot(dx, dy)


def upsert(conn: sqlite3.Connection, source: str, items: list[Imported]) -> Stats:
    """Apply a full import of one source. Rows of `source` not in items go 'gone'."""
    stats = Stats()
    seen = set()
    with conn:
        for item in items:
            seen.add(item.ext_id)
            row = conn.execute("SELECT id, edited, gone FROM place WHERE ext_id = ?", (item.ext_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO place (category_key, ext_id, source, name, lat, lon, address, lap_score, also)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (item.category, item.ext_id, item.source, item.name, item.lat, item.lon,
                     item.address, item.lap_score, item.also),
                )
                stats.added += 1
                continue
            if row["gone"]:
                stats.revived += 1
            if row["edited"]:
                conn.execute("UPDATE place SET gone = 0, lap_score = ?, also = ? WHERE id = ?",
                             (item.lap_score, item.also, row["id"]))
                stats.kept_edited += 1
                continue
            conn.execute(
                "UPDATE place SET category_key=?, name=?, lat=?, lon=?, address=?, lap_score=?, also=?, gone=0"
                " WHERE id = ?",
                (item.category, item.name, item.lat, item.lon, item.address, item.lap_score, item.also, row["id"]),
            )
            stats.updated += 1
        for row in conn.execute("SELECT id, ext_id FROM place WHERE source = ? AND gone = 0", (source,)).fetchall():
            if row["ext_id"] not in seen:
                conn.execute("UPDATE place SET gone = 1 WHERE id = ?", (row["id"],))
                stats.gone += 1
    return stats


# -- OpenStreetMap ---------------------------------------------------------

def _address(tags: dict) -> str:
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    return street


def osm_places(pbf: Path, bbox: list[float]) -> list[Imported]:
    """Read places from a PBF extract, clipped to bbox (west, south, east, north)."""
    import osmium  # imported late: only the import command needs it

    west, south, east, north = bbox
    keys = osmium.filter.KeyFilter("shop", "amenity", "leisure")
    out: list[Imported] = []
    # locations first: the filter drops untagged nodes, which ways need for geometry
    processor = (osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY | osmium.osm.RELATION | osmium.osm.AREA)
                 .with_locations().with_areas(keys).with_filter(keys))
    for obj in processor:
        if not obj.tags:
            continue
        if not (obj.is_node() or obj.is_area()):
            continue  # ways and relations are read only to build areas
        tags = {t.k: t.v for t in obj.tags}
        key = categories.classify(tags)
        if key is None:
            continue
        if obj.is_node():
            lon, lat = obj.location.lon, obj.location.lat
            ext = f"osm:n{obj.id}"
        else:
            points = []
            for ring in obj.outer_rings():
                ring_points = [(n.lon, n.lat) for n in ring if n.location.valid()]
                points += ring_points[:-1]  # a ring repeats its first point at the end
            if not points:
                continue
            lon = sum(p[0] for p in points) / len(points)
            lat = sum(p[1] for p in points) / len(points)
            ext = f"osm:{'w' if obj.from_way() else 'r'}{obj.orig_id()}"
        if not (west <= lon <= east and south <= lat <= north):
            continue
        name = tags.get("name") or ""
        if not name and key != "lap_pool":
            name = categories.BUILTIN_NAMES.get(key, key)
        out.append(Imported(
            ext_id=ext, category=key, name=name or "Swimming pool", lat=lat, lon=lon, source="osm",
            address=_address(tags),
            lap_score=categories.lap_likelihood(tags) if key == "lap_pool" else None,
        ))
    return out


def import_osm(conn: sqlite3.Connection, pbf: Path, bbox: list[float]) -> Stats:
    return upsert(conn, "osm", osm_places(pbf, bbox))


# -- Chicago Park District pools -------------------------------------------

def parse_park_district(rows: list[dict]) -> list[Imported]:
    """Rows of the Park District facility dataset (public domain) that are pools."""
    out = []
    for row in rows:
        facility = (row.get("facility_name") or "").upper()
        if "POOL" not in facility:
            continue
        loc = row.get("location") or {}
        try:
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        indoor = "INDOOR" in facility
        park = (row.get("park") or "").title()
        out.append(Imported(
            ext_id=f"pd:{row.get('park_number', '')}:{'in' if indoor else 'out'}",
            category="lap_pool",
            name=f"{park} pool ({'indoor' if indoor else 'outdoor, seasonal'})",
            lat=lat, lon=lon, source="park_district",
            lap_score="likely" if indoor else "maybe",
            also="Chicago Park District",
        ))
    return out


def merge_with_osm(conn: sqlite3.Connection, pools: list[Imported]) -> list[Imported]:
    """Drop Park District pools that an OSM candidate already covers (within 100 m).

    The OSM candidate is upgraded to 'likely' and remembers the match in `also`.
    """
    osm = conn.execute(
        "SELECT id, lat, lon, lap_score FROM place WHERE category_key = 'lap_pool' AND source = 'osm' AND gone = 0"
    ).fetchall()
    keep = []
    with conn:
        for pool in pools:
            match = next((o for o in osm if metres_between(o["lat"], o["lon"], pool.lat, pool.lon) <= MERGE_RADIUS_M), None)
            if match is None:
                keep.append(pool)
                continue
            conn.execute(
                "UPDATE place SET lap_score = CASE WHEN lap_score = 'unlikely' THEN lap_score ELSE 'likely' END,"
                " also = ? WHERE id = ?",
                (f"Chicago Park District: {pool.name}", match["id"]),
            )
    return keep


def import_pools(conn: sqlite3.Connection, rows: list[dict]) -> Stats:
    return upsert(conn, "park_district", merge_with_osm(conn, parse_park_district(rows)))


# -- CTA stops as places ---------------------------------------------------

def cta_stop_places(stops_geojson: Path) -> list[Imported]:
    data = json.loads(stops_geojson.read_text(encoding="utf-8"))
    out = []
    for feature in data["features"]:
        props, (lon, lat) = feature["properties"], feature["geometry"]["coordinates"]
        out.append(Imported(
            ext_id=f"cta:{props['id']}", category="rail_station" if props["kind"] == "rail" else "bus_stop",
            name=props["name"], lat=lat, lon=lon, source="cta",
        ))
    return out


def import_cta_stops(conn: sqlite3.Connection) -> Stats:
    return upsert(conn, "cta", cta_stop_places(config.cache_dir() / "cta" / "stops.geojson"))
