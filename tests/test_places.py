"""Place classification, import and the places API, on made-up places."""

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from aptscout import categories, db, importer  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(categories.classify({"shop": "supermarket"}), "grocery")
        self.assertEqual(categories.classify({"shop": "convenience"}), "convenience")
        self.assertEqual(categories.classify({"leisure": "fitness_centre"}), "gym")
        self.assertEqual(categories.classify({"leisure": "sports_centre", "sport": "fitness"}), "gym")
        self.assertEqual(categories.classify({"leisure": "swimming_pool"}), "lap_pool")
        self.assertEqual(categories.classify({"leisure": "sports_centre", "sport": "swimming;tennis"}), "lap_pool")
        self.assertEqual(categories.classify({"leisure": "park", "name": "Test Green"}), "park")
        self.assertIsNone(categories.classify({"leisure": "park"}))  # unnamed
        self.assertIsNone(categories.classify({"shop": "bakery"}))

    def test_lap_likelihood(self):
        L = categories.lap_likelihood
        self.assertEqual(L({"name": "Test Aquatic Center", "length": "25 m"}), "likely")
        self.assertEqual(L({"name": "Test Pool", "lanes": "6"}), "likely")
        self.assertEqual(L({"name": "Test Pool", "length": "75 ft"}), "likely")  # 22.9 m
        self.assertEqual(L({"name": "Test Pool", "length": "12"}), "maybe")
        self.assertEqual(L({"name": "Test Pool", "access": "private"}), "unlikely")
        self.assertEqual(L({"name": "Test Pool", "swimming_pool": "hot_tub"}), "unlikely")
        self.assertEqual(L({"name": "Fictional Towers Apartments Pool"}), "unlikely")
        self.assertEqual(L({}), "unlikely")  # unnamed, no cue
        self.assertEqual(L({"operator": "Test District"}), "maybe")


def item(ext, name="Test Store", lat=41.0, lon=-87.6, category="grocery", source="osm", **kw):
    return importer.Imported(ext_id=ext, category=category, name=name, lat=lat, lon=lon, source=source, **kw)


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        self.addCleanup(self.conn.close)

    def names(self):
        return {r["ext_id"]: (r["name"], r["gone"]) for r in self.conn.execute("SELECT * FROM place")}

    def test_reimport_keeps_edits_and_flags_gone(self):
        importer.upsert(self.conn, "osm", [item("osm:n1", "Old Name"), item("osm:n2", "Second")])
        self.conn.execute("UPDATE place SET name = 'My Name', edited = 1 WHERE ext_id = 'osm:n1'")
        self.conn.commit()
        stats = importer.upsert(self.conn, "osm", [item("osm:n1", "New Name"), item("osm:n3", "Third")])
        self.assertEqual((stats.added, stats.kept_edited, stats.gone), (1, 1, 1))
        self.assertEqual(self.names(), {"osm:n1": ("My Name", 0), "osm:n2": ("Second", 1), "osm:n3": ("Third", 0)})
        stats = importer.upsert(self.conn, "osm", [item("osm:n2", "Second again")])
        self.assertEqual(stats.revived, 1)
        self.assertEqual(self.names()["osm:n2"], ("Second again", 0))

    def test_other_sources_are_not_flagged_gone(self):
        importer.upsert(self.conn, "cta", [item("cta:1", source="cta")])
        importer.upsert(self.conn, "osm", [item("osm:n1")])
        self.assertEqual(self.names()["cta:1"][1], 0)

    def test_park_district_pools_merge_with_osm(self):
        importer.upsert(self.conn, "osm", [item("osm:w9", "Fictional Natatorium", 41.9000, -87.7000,
                                                category="lap_pool", lap_score="maybe")])
        rows = [
            {"park": "TESTVILLE", "park_number": "1", "facility_name": "POOL (INDOOR)",
             "location": {"latitude": "41.9004", "longitude": "-87.7000"}},       # 44 m from the OSM pool
            {"park": "ELSEWHERE", "park_number": "2", "facility_name": "POOL (OUTDOOR)",
             "location": {"latitude": "41.8000", "longitude": "-87.6000"}},
            {"park": "NOPE", "park_number": "3", "facility_name": "PLAYGROUND", "location": {"latitude": "1", "longitude": "1"}},
        ]
        stats = importer.import_pools(self.conn, rows)
        self.assertEqual(stats.added, 1)
        osm = self.conn.execute("SELECT lap_score, also FROM place WHERE ext_id = 'osm:w9'").fetchone()
        self.assertEqual(osm["lap_score"], "likely")
        self.assertIn("Testville", osm["also"])
        outdoor = self.conn.execute("SELECT lap_score, name FROM place WHERE ext_id = 'pd:2:out'").fetchone()
        self.assertEqual(outdoor["lap_score"], "maybe")
        self.assertIn("seasonal", outdoor["name"])


class OsmReadTest(unittest.TestCase):
    def test_nodes_and_areas_from_a_tiny_extract(self):
        import osmium

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pbf = Path(tmp.name) / "tiny.osm.pbf"
        M = osmium.osm.mutable
        with osmium.SimpleWriter(str(pbf)) as w:
            w.add_node(M.Node(id=1, location=(-87.60, 41.00), tags={"shop": "supermarket", "name": "Fictional Foods"}))
            for i, (lon, lat) in enumerate([(-87.70, 41.10), (-87.69, 41.10), (-87.69, 41.11), (-87.70, 41.11)], start=10):
                w.add_node(M.Node(id=i, location=(lon, lat)))
            w.add_node(M.Node(id=20, location=(10.0, 10.0), tags={"shop": "supermarket", "name": "Far Away"}))
            w.add_way(M.Way(id=5, nodes=[10, 11, 12, 13, 10], tags={"leisure": "park", "name": "Test Green"}))
        found = {p.name: p for p in importer.osm_places(pbf, [-88.0, 40.9, -87.5, 41.5])}
        self.assertEqual(set(found), {"Fictional Foods", "Test Green"})  # Far Away is outside the box
        self.assertEqual(found["Fictional Foods"].ext_id, "osm:n1")
        green = found["Test Green"]
        self.assertEqual((green.category, green.ext_id), ("park", "osm:w5"))
        self.assertAlmostEqual(green.lon, -87.695, places=3)
        self.assertAlmostEqual(green.lat, 41.105, places=3)


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class PlacesApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (unittest.mock.patch.dict(os.environ, {"APTSCOUT_DATA_DIR": self.tmp.name, "APTSCOUT_DEV_USER": "alex"}),):
            patcher.start()
            self.addCleanup(patcher.stop)
        conn = db.connect()
        importer.upsert(conn, "osm", [
            item("osm:n1", "Fictional Foods", 41.0, -87.6),
            item("osm:n2", "Test Natatorium", 41.1, -87.6, category="lap_pool", lap_score="likely"),
        ])
        conn.close()
        import aptscout.app as app_module

        self.client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none"))

    def places(self, **params):
        return self.client.get("/api/places", params=params).json()["features"]

    def test_requires_sign_in(self):
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": ""}):
            self.assertEqual(self.client.get("/api/places").status_code, 401)

    def test_categories_are_seeded(self):
        keys = [c["key"] for c in self.client.get("/api/categories").json()]
        self.assertIn("lap_pool", keys)
        self.assertEqual(keys[0], "grocery")

    def test_add_edit_and_remove_categories(self):
        created = self.client.post("/api/categories", json={"name": "Climbing gym", "colour": "#aa3300"})
        self.assertEqual(created.status_code, 201)
        key = created.json()["key"]
        self.assertEqual(self.client.post("/api/categories", json={"name": "Climbing gym", "colour": "#aa3300"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/categories/{key}", json={"weight": 8}).json()["weight"], 8)
        self.assertEqual(self.client.patch(f"/api/categories/{key}", json={"measure": "teleport"}).status_code, 422)
        self.assertEqual(self.client.delete("/api/categories/grocery").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/categories/{key}").status_code, 204)

    def test_manual_place_and_marks(self):
        made = self.client.post("/api/places", json={"category": "grocery", "name": "Test Corner Shop", "lat": 41.5, "lon": -87.5})
        self.assertEqual(made.status_code, 201)
        self.assertEqual(self.client.post("/api/places", json={"category": "nope", "name": "x", "lat": 0, "lon": 0}).status_code, 422)
        pool = next(f for f in self.places() if f["properties"]["category"] == "lap_pool")["properties"]
        self.assertEqual(pool["state"], "unreviewed")
        self.client.patch(f"/api/places/{pool['id']}", json={"state": "confirmed", "favourite": True, "notes": "25 m, six lanes"})
        pool = next(f for f in self.places() if f["properties"]["category"] == "lap_pool")["properties"]
        self.assertEqual((pool["state"], pool["favourite"], pool["notes"]), ("confirmed", True, "25 m, six lanes"))
        self.assertEqual(self.client.patch(f"/api/places/{pool['id']}", json={"state": "maybe"}).status_code, 422)
        # an edit of an imported place keeps it from being overwritten by a re-import
        self.client.patch(f"/api/places/{pool['id']}", json={"name": "Renamed Pool"})
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT edited FROM place WHERE id = ?", (pool["id"],)).fetchone()[0], 1)
        conn.close()

    def test_delete_hides_imported_and_removes_own(self):
        food = next(f for f in self.places() if f["properties"]["name"] == "Fictional Foods")["properties"]["id"]
        self.assertEqual(self.client.delete(f"/api/places/{food}").status_code, 204)
        self.assertNotIn("Fictional Foods", [f["properties"]["name"] for f in self.places()])
        self.assertIn("Fictional Foods", [f["properties"]["name"] for f in self.places(include_hidden=True)])
        own = self.client.post("/api/places", json={"category": "gym", "name": "Home Gym", "lat": 41.2, "lon": -87.2}).json()["id"]
        self.client.delete(f"/api/places/{own}")
        self.assertNotIn("Home Gym", [f["properties"]["name"] for f in self.places(include_hidden=True)])

    def test_owners_do_not_see_each_others_places(self):
        self.client.post("/api/places", json={"category": "gym", "name": "Alex Gym", "lat": 41.2, "lon": -87.2})
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": "sam"}):
            names = [f["properties"]["name"] for f in self.places()]
            self.assertIn("Fictional Foods", names)
            self.assertNotIn("Alex Gym", names)

    def test_transit_places_only_on_request(self):
        conn = db.connect()
        importer.upsert(conn, "cta", [item("cta:1", "Test Station", category="rail_station", source="cta")])
        conn.close()
        self.assertNotIn("Test Station", [f["properties"]["name"] for f in self.places()])
        self.assertIn("Test Station", [f["properties"]["name"] for f in self.places(include_transit="true")])


if __name__ == "__main__":
    unittest.main()
