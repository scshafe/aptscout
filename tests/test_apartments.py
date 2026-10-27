"""Apartments, scoring, routing and geocoding clients, on made-up places."""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from aptscout import categories, db, geocode, importer, routing, scoring  # noqa: E402

# One degree of latitude is 111.2 km; at 4.8 km/h a walking minute is 80 m.
M_PER_DEG_LAT = 111194.9
ORIGIN = (41.9000, -87.6500)


def north(metres: float) -> tuple[float, float]:
    return (ORIGIN[0] + metres / M_PER_DEG_LAT, ORIGIN[1])


def place(ext, name, metres, category="grocery"):
    lat, lon = north(metres)
    return importer.Imported(ext_id=ext, category=category, name=name, lat=lat, lon=lon, source="osm")


class CurveTest(unittest.TestCase):
    def test_curve(self):
        self.assertEqual(scoring.curve(3, 5, 20), 100)
        self.assertEqual(scoring.curve(5, 5, 20), 100)
        self.assertEqual(scoring.curve(12.5, 5, 20), 50)
        self.assertEqual(scoring.curve(20, 5, 20), 0)
        self.assertEqual(scoring.curve(40, 5, 20), 0)


class RoutingTest(unittest.TestCase):
    def test_straight_line_walk_minutes(self):
        got = routing.StraightLine().walk_minutes(ORIGIN, [north(400), north(800)], "straight")
        self.assertAlmostEqual(got[0], 5.0, places=1)
        self.assertAlmostEqual(got[1], 10.0, places=1)
        detour = routing.StraightLine().walk_minutes(ORIGIN, [north(400)], "walk_time")
        self.assertAlmostEqual(detour[0], 6.5, places=1)  # x1.3 for the street network

    def test_valhalla_request_and_parse(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"sources_to_targets": [[
                {"from_index": 0, "to_index": 1, "distance": 0.48, "time": 420},
                {"from_index": 0, "to_index": 0, "distance": 0.96, "time": None},  # unreachable
            ]]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        valhalla = routing.Valhalla("http://valhalla.test:8002/", client)
        time = valhalla.walk_minutes(ORIGIN, [north(100), north(200)], "walk_time")
        self.assertEqual(time, [None, 7.0])
        dist = valhalla.walk_minutes(ORIGIN, [north(100), north(200)], "walk_distance")
        self.assertAlmostEqual(dist[1], 6.0, places=2)  # 480 m at 80 m/min
        self.assertEqual(seen["url"], "http://valhalla.test:8002/sources_to_targets")
        self.assertEqual(seen["body"]["costing"], "pedestrian")
        self.assertEqual(len(seen["body"]["targets"]), 2)


class GeocodeTest(unittest.TestCase):
    def test_parse_skips_bad_rows(self):
        got = geocode.parse([{"display_name": "1 Test St", "lat": "41.9", "lon": "-87.6"}, {"lat": "x"}])
        self.assertEqual(got, [{"label": "1 Test St", "lat": 41.9, "lon": -87.6}])

    def test_not_configured(self):
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_NOMINATIM_URL": ""}):
            with self.assertRaises(geocode.NotConfigured):
                geocode.search("1 Test St")

    def test_search_asks_the_configured_server(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json=[{"display_name": "1 Test St", "lat": "41.9", "lon": "-87.6"}])

        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_NOMINATIM_URL": "http://nominatim.test/"}):
            got = geocode.search("1 Test St", [-88.0, 41.6, -87.5, 42.1], httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(got[0]["lat"], 41.9)
        self.assertTrue(seen["url"].startswith("http://nominatim.test/search?"))
        self.assertIn("viewbox=-88.0%2C42.1%2C-87.5%2C41.6", seen["url"])


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class ApartmentApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {
            "APTSCOUT_DATA_DIR": self.tmp.name, "APTSCOUT_DEV_USER": "alex", "APTSCOUT_NOMINATIM_URL": "",
            "APTSCOUT_VALHALLA_URL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        conn = db.connect()
        importer.upsert(conn, "osm", [
            place("osm:n1", "Fictional Foods", 240),             # 3 min straight
            place("osm:n2", "Test Mart", 1000),                  # 12.5 min straight
            place("osm:n3", "Far Market", 5000),                 # beyond 20 min
            place("osm:n4", "Test Natatorium", 800, "lap_pool"),
        ])
        conn.close()
        import aptscout.app as app_module

        self.client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none"))
        # score only grocery and lap pools, straight line, to keep the arithmetic readable
        for cat in self.client.get("/api/categories").json():
            weight = {"grocery": 6, "lap_pool": 2}.get(cat["key"], 0)
            self.client.patch(f"/api/categories/{cat['key']}", json={"weight": weight, "measure": "straight"})

    def make(self, **kw):
        lat, lon = ORIGIN
        body = {"label": "Test flat", "address": "1 Fictional Ave", "lat": lat, "lon": lon, "rent": 1800, **kw}
        resp = self.client.post("/api/apartments", json=body)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def test_create_read_and_validate(self):
        aid = self.make(facing=["SE", "N"], floor=4, status="toured", listing_url="https://example.test/l/1")
        got = self.client.get(f"/api/apartments/{aid}").json()
        self.assertEqual(got["facing"], ["N", "SE"])
        self.assertEqual(got["location_source"], "manual")
        self.assertEqual([h["status"] for h in got["status_history"]], ["toured"])
        for bad in ({"facing": ["UP"]}, {"status": "dreaming"}, {"rent": -1}, {"listing_url": "javascript:x"},
                    {"lat": 41.9, "lon": None}):
            body = {"label": "x", **bad}
            self.assertEqual(self.client.post("/api/apartments", json=body).status_code, 422, bad)

    def test_apartment_without_a_pin_is_allowed(self):
        resp = self.client.post("/api/apartments", json={"address": "2 Fictional Ave", "rent": 1500})
        self.assertEqual(resp.status_code, 201)
        got = self.client.get(f"/api/apartments/{resp.json()['id']}").json()
        self.assertIsNone(got["score"]["place_score"])
        self.assertEqual(got["location_source"], "none")

    def test_scores_and_explanation(self):
        aid = self.make()
        score = self.client.get(f"/api/apartments/{aid}").json()["score"]
        by_key = {c["key"]: c for c in score["categories"]}
        self.assertEqual(by_key["grocery"]["place"]["name"], "Fictional Foods")
        self.assertEqual(by_key["grocery"]["score"], 100)       # 3 min <= d_good 5
        self.assertEqual(by_key["lap_pool"]["score"], 0)        # unconfirmed pool does not count
        self.assertIn("none within", by_key["lap_pool"]["note"])
        self.assertEqual(score["place_score"], 75.0)            # (100*6 + 0*2) / 8
        pool = next(f for f in self.client.get("/api/places").json()["features"] if f["properties"]["category"] == "lap_pool")
        self.client.patch(f"/api/places/{pool['properties']['id']}", json={"state": "confirmed"})
        score = self.client.get(f"/api/apartments/{aid}").json()["score"]
        by_key = {c["key"]: c for c in score["categories"]}
        self.assertEqual(by_key["lap_pool"]["minutes"], 10.0)   # 800 m
        self.assertEqual(by_key["lap_pool"]["score"], 66.7)     # (20-10)/(20-5)
        self.assertEqual(score["place_score"], 91.7)            # (100*6 + 66.7*2) / 8

    def test_favourite_counts_instead_of_nearest(self):
        aid = self.make()
        mart = next(f for f in self.client.get("/api/places").json()["features"] if f["properties"]["name"] == "Test Mart")
        self.client.patch(f"/api/places/{mart['properties']['id']}", json={"favourite": True})
        self.client.patch("/api/categories/grocery", json={"aggregation": "favourite"})
        grocery = {c["key"]: c for c in self.client.get(f"/api/apartments/{aid}").json()["score"]["categories"]}["grocery"]
        self.assertEqual(grocery["place"]["name"], "Test Mart")
        self.assertEqual(grocery["minutes"], 12.5)
        self.assertEqual(grocery["score"], 50.0)

    def test_moving_the_pin_drops_cached_distances(self):
        aid = self.make()
        self.client.get(f"/api/apartments/{aid}")
        conn = db.connect()
        self.assertGreater(conn.execute("SELECT count(*) FROM apartment_distance").fetchone()[0], 0)
        conn.close()
        lat, lon = north(2000)
        self.assertEqual(self.client.patch(f"/api/apartments/{aid}", json={"lat": lat, "lon": lon}).status_code, 200)
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT count(*) FROM apartment_distance").fetchone()[0], 0)
        conn.close()

    def test_patch_keeps_unsent_fields_and_records_status(self):
        aid = self.make(floor=3, notes="sunny")
        self.client.patch(f"/api/apartments/{aid}", json={"status": "applied", "rent": 1750})
        got = self.client.get(f"/api/apartments/{aid}").json()
        self.assertEqual((got["rent"], got["floor"], got["notes"], got["status"]), (1750, 3, "sunny", "applied"))
        self.assertEqual([h["status"] for h in got["status_history"]], ["interested", "applied"])
        self.assertEqual(self.client.patch(f"/api/apartments/{aid}", json={"rent": "a lot"}).status_code, 422)

    def test_owners_are_separate(self):
        aid = self.make()
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": "sam"}):
            self.assertEqual(self.client.get(f"/api/apartments/{aid}").status_code, 404)
            self.assertEqual(self.client.get("/api/apartments").json(), [])
            self.assertEqual(self.client.delete(f"/api/apartments/{aid}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/apartments/{aid}").status_code, 204)

    def test_list_has_scores_and_geocode_without_a_server(self):
        self.make()
        listed = self.client.get("/api/apartments").json()
        self.assertEqual(listed[0]["place_score"], 75.0)
        self.assertEqual(listed[0]["minutes"]["grocery"], 3.0)
        self.assertEqual(self.client.get("/api/geocode", params={"q": "1 Fictional Ave"}).status_code, 503)


if __name__ == "__main__":
    unittest.main()
