"""Destinations, the simple transit model and the weekly travel time, on made-up places."""

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

from aptscout import db, importer, routing, transit  # noqa: E402

M_PER_DEG_LAT = 111194.9
ORIGIN = (41.9000, -87.6500)


def north(metres, east=0.0):
    return (ORIGIN[0] + metres / M_PER_DEG_LAT, ORIGIN[1] + east / (M_PER_DEG_LAT * 0.7431))


def place(ext, name, metres, category="grocery", source="osm", east=0.0):
    lat, lon = north(metres, east)
    return importer.Imported(ext_id=ext, category=category, name=name, lat=lat, lon=lon, source=source)


class TransitModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        self.addCleanup(self.conn.close)
        importer.upsert(self.conn, "cta", [
            place("cta:1", "Fictional Square", 300, "rail_station", "cta"),
            place("cta:2", "Test Terminal", 9300, "rail_station", "cta"),   # 9 km north of the first
        ])

    def test_rail_beats_walking_on_a_long_trip(self):
        minutes, method = transit.estimate(self.conn, north(0), north(9600), "weekday_rush")
        self.assertEqual(method, "rail")
        # walk 300 m (x1.3) + wait 2.5 + ride 9 km x 1.2 at 30 km/h + 6 transfer + walk 300 m
        self.assertAlmostEqual(minutes, 4.9 + 2.5 + 21.6 + 6 + 4.9, delta=1.0)
        walking = routing.walk_minutes(9600 * routing.DETOUR)
        self.assertLess(minutes, walking)

    def test_short_trip_is_walked_and_no_stops_means_walk(self):
        self.assertEqual(transit.estimate(self.conn, north(0), north(400), "weekday_rush")[1], "walk")
        self.assertEqual(transit.estimate(self.conn, north(0, 90000), north(9600, 90000), "sunday")[1], "walk")

    def test_waits_depend_on_the_time_band(self):
        rush = transit.estimate(self.conn, north(0), north(9600), "weekday_rush")[0]
        sunday = transit.estimate(self.conn, north(0), north(9600), "sunday")[0]
        self.assertAlmostEqual(sunday - rush, (12 - 5) / 2, places=3)


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class WeeklyApiTest(unittest.TestCase):
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
            place("osm:n1", "Fictional Foods", 400),     # 400 m north
            place("osm:n2", "Test Mart", 1600),
            place("osm:n3", "Test Gym", 800, "gym"),
        ])
        conn.close()
        import aptscout.app as app_module

        self.client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none"))
        lat, lon = ORIGIN
        self.apt = self.client.post("/api/apartments", json={"address": "1 Fictional Ave", "lat": lat, "lon": lon, "rent": 1800}).json()["id"]

    def weekly(self):
        return self.client.get(f"/api/apartments/{self.apt}").json()["weekly"]

    def add(self, **kw):
        body = {"name": "Groceries", "kind": "category", "category_key": "grocery", "trips_per_week": 2, "mode": "walk", **kw}
        resp = self.client.post("/api/destinations", json=body)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def test_category_destination_walks_to_the_best_store(self):
        self.add()
        w = self.weekly()
        part = w["destinations"][0]
        self.assertEqual(part["place"]["name"], "Fictional Foods")
        # 400 m x 1.3 detour at 80 m/min = 6.5 min each way
        self.assertEqual((part["out"], part["back"], part["round_trip"]), (6.5, 6.5, 13.0))
        self.assertEqual(part["weekly"], 26.0)       # 2 trips
        self.assertEqual(w["total"], 26.0)
        self.assertTrue(w["complete"])

    def test_modes_have_their_own_speeds(self):
        walk = self.add(name="Gym walk", category_key="gym", trips_per_week=1)
        bike = self.add(name="Gym bike", category_key="gym", trips_per_week=1, mode="bike")
        drive = self.add(name="Gym drive", category_key="gym", trips_per_week=1, mode="drive", time_band="weekday_rush")
        by = {p["id"]: p for p in self.weekly()["destinations"]}
        self.assertEqual(by[walk]["round_trip"], 26.0)       # 800 m x 1.3 / 80 m/min = 13 each way
        self.assertAlmostEqual(by[bike]["round_trip"], 8.3, places=1)    # 1040 m at 250 m/min
        self.assertAlmostEqual(by[drive]["round_trip"], 5.8, delta=0.1)   # 1040 m at 28 km/h = 2.23 min, x 1.3 in the rush, twice

    def test_selection_rules(self):
        fav = next(f for f in self.client.get("/api/places").json()["features"] if f["properties"]["name"] == "Test Mart")
        self.client.patch(f"/api/places/{fav['properties']['id']}", json={"favourite": True})
        best = self.add(name="best")
        fav_id = self.add(name="fav", selection_rule="favourite")
        mean = self.add(name="mean", selection_rule="mean_n", n=2)
        by = {p["id"]: p for p in self.weekly()["destinations"]}
        self.assertEqual(by[best]["place"]["name"], "Fictional Foods")
        self.assertEqual(by[fav_id]["place"]["name"], "Test Mart")
        self.assertEqual(by[fav_id]["round_trip"], 52.0)     # 1600 m x 1.3 / 80 = 26 each way
        self.assertEqual(by[mean]["round_trip"], (13.0 + 52.0) / 2)
        self.assertIn("mean of the nearest 2", by[mean]["note"])

    def test_point_destination_and_budget(self):
        job = self.add(name="Job", kind="place", category_key=None, lat=north(4000)[0], lon=ORIGIN[1],
                       trips_per_week=5, mode="drive", time_band="weekday_rush", max_minutes=5)
        part = next(p for p in self.weekly()["destinations"] if p["id"] == job)
        self.assertEqual(part["place"]["name"], "Job")
        self.assertTrue(part["over_budget"])        # 4 km x 1.3 at 28 km/h x 1.3 = 14.5 min each way
        self.assertEqual(part["weekly"], round(part["round_trip"] * 5, 1))

    def test_changes_recompute_only_what_they_touch(self):
        dest = self.add()
        self.weekly()
        conn = db.connect()
        count = lambda: conn.execute("SELECT count(*) FROM travel_time").fetchone()[0]
        self.assertEqual(count(), 4)                 # two candidate stores, out and back
        self.client.patch(f"/api/destinations/{dest}", json={"trips_per_week": 5})
        self.assertEqual(count(), 4)                 # trips are a multiplier: cache kept
        self.assertEqual(self.weekly()["total"], 65.0)
        self.client.patch(f"/api/destinations/{dest}", json={"mode": "bike"})
        self.assertEqual(count(), 0)                 # a new mode needs new times
        conn.close()

    def test_validation_and_ownership(self):
        for bad in ({"mode": "teleport"}, {"time_band": "midnight"}, {"kind": "thing"}, {"trips_per_week": -1},
                    {"category_key": "nope"}, {"kind": "category", "category_key": None}):
            body = {"name": "x", "kind": "category", "category_key": "grocery", **bad}
            self.assertEqual(self.client.post("/api/destinations", json=body).status_code, 422, bad)
        dest = self.add()
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": "sam"}):
            self.assertEqual(self.client.delete(f"/api/destinations/{dest}").status_code, 404)
            self.assertEqual(self.client.get("/api/destinations").json(), [])

    def test_list_carries_the_weekly_parts_and_settings(self):
        dest = self.add()
        row = self.client.get("/api/apartments").json()[0]
        self.assertEqual(row["weekly_minutes"], 26.0)
        self.assertEqual(row["weekly_parts"], [{"id": dest, "round_trip": 13.0, "trips": 2.0, "weekly": 26.0}])
        self.assertFalse(self.client.get("/api/settings").json()["combined_on"])
        self.assertEqual(self.client.put("/api/settings", json={"combined_on": True, "w_time": 9}).json()["w_time"], 9)
        self.assertEqual(self.client.put("/api/settings", json={"w_time": 99}).status_code, 422)
        self.assertEqual(self.client.put("/api/settings", json={"unknown": 1}).status_code, 422)

    def test_apartment_without_a_pin_has_no_weekly_total(self):
        self.add()
        nopin = self.client.post("/api/apartments", json={"address": "2 Fictional Ave"}).json()["id"]
        self.assertIsNone(self.client.get(f"/api/apartments/{nopin}").json()["weekly"]["total"])


if __name__ == "__main__":
    unittest.main()
