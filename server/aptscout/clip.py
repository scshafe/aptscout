"""Clip an OSM extract to a bounding box, keeping whole ways (for OpenTripPlanner).

OTP builds its street graph from a PBF. The Illinois extract is far larger than
the city, so the graph would need much more memory than the city does. Three
passes over the file: nodes in the box, ways touching them, then the nodes those
ways use. Relations are dropped (turn restrictions and route relations are
not needed to walk to a stop).
"""

from pathlib import Path


def clip(src: Path, dest: Path, bbox: list[float]) -> dict:
    import osmium

    west, south, east, north = bbox
    inside: set[int] = set()
    for n in osmium.FileProcessor(str(src), osmium.osm.NODE):
        if west <= n.lon <= east and south <= n.lat <= north:
            inside.add(n.id)

    way_ids: set[int] = set()
    needed: set[int] = set()
    for w in osmium.FileProcessor(str(src), osmium.osm.WAY):
        refs = [r.ref for r in w.nodes]
        if any(r in inside for r in refs):
            way_ids.add(w.id)
            needed.update(refs)

    tmp = dest.with_name(dest.name + ".part.osm.pbf")
    tmp.unlink(missing_ok=True)
    counts = {"nodes": 0, "ways": 0}
    with osmium.SimpleWriter(str(tmp)) as writer:
        for obj in osmium.FileProcessor(str(src), osmium.osm.NODE | osmium.osm.WAY):
            if obj.is_node():
                if obj.id in needed:
                    writer.add_node(obj)
                    counts["nodes"] += 1
            elif obj.id in way_ids:
                writer.add_way(obj)
                counts["ways"] += 1
    tmp.replace(dest)
    return counts
