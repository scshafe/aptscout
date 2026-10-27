"""Schedule-based transit: the OTP client, service dates, fallbacks, stale handling and the OSM clip."""

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from aptscout import clip, config, datasets, db, importer, otp, recompute, routing, weekly  # noqa: E402

M_PER_DEG_LAT = 111194.9
ORIGIN = (41.9000, -87.6500)


def north(metres):
    return (ORIGIN[0] + metres / M_PER_DEG_LAT, ORIGIN[1])


def mock_otp(durations, seen=None, legacy=False):
    """An OTP whose itineraries last `durations` seconds, in order of the calls.

    A modern OTP answers planConnection; with legacy=True it only knows plan.
    """
    calls = iter(durations)

    def handler(request):
        body = json.loads(request.content)
        if legacy and "planConnection" in body["query"]:
            return httpx.Response(200, json={"errors": [{"message": "Validation error (FieldUndefined@[planConnection]) : Field 'planConnection' in type 'QueryType' is undefined"}]})
        if seen is not None:
            seen.append(body["variables"])
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        if value == "error":
            return httpx.Response(200, json={"errors": [{"message": "no path"}], "data": None})
        durations_ = [] if value is None else [value, value + 600]
        if legacy:
            return httpx.Response(200, json={"data": {"plan": {"itineraries": [{"duration": d} for d in durations_]}}})
        return httpx.Response(200, json={"data": {"planConnection": {"edges": [{"node": {"duration": d}} for d in durations_]}}})

    return httpx.Client(transport=httpx.MockTransport(handler))


class ServiceDateTest(unittest.TestCase):
    def test_next_day_of_the_kind(self):
        tue = date(2026, 10, 27)
        self.assertEqual(otp.service_date("weekday_rush", tue, None), date(2026, 10, 28))   # Wednesday
        self.assertEqual(otp.service_date("saturday", tue, None), date(2026, 10, 31))
        self.assertEqual(otp.service_date("sunday", tue, None), date(2026, 11, 1))

    def test_stays_inside_the_feed(self):
        self.assertEqual(otp.service_date("saturday", date(2026, 10, 27), date(2026, 10, 25)), date(2026, 10, 24))
        self.assertEqual(otp.service_date("weekday_midday", date(2026, 10, 27), date(2026, 10, 27)), date(2026, 10, 21))


class OtpClientTest(unittest.TestCase):
    def test_median_of_the_best_itinerary_at_each_departure(self):
        seen = []
        engine = otp.Otp("http://otp.test:8080/", mock_otp([1200, 1800, 1500], seen), today=date(2026, 10, 27), valid_to=date(2026, 11, 30))
        minutes, method = engine.minutes(ORIGIN, north(3000), "weekday_rush", "out")
        self.assertEqual((minutes, method), (25.0, "otp"))             # median of 20, 30, 25
        self.assertEqual([v["dateTime"] for v in seen], ["2026-10-28T07:30:00-05:00", "2026-10-28T08:00:00-05:00", "2026-10-28T08:30:00-05:00"])
        self.assertEqual((seen[0]["from"], seen[0]["fromLon"]), (ORIGIN[0], ORIGIN[1]))

    def test_an_older_otp_is_asked_with_plan(self):
        seen = []
        engine = otp.Otp("http://otp.test", mock_otp([600, 900, 1200], seen, legacy=True), today=date(2026, 10, 27), valid_to=None)
        self.assertEqual(engine.minutes(ORIGIN, north(3000), "weekday_rush", "out")[0], 15.0)
        self.assertEqual([v["time"] for v in seen], ["07:30:00", "08:00:00", "08:30:00"])   # hh:mm:ss, as OTP requires
        self.assertFalse(engine.modern)

    def test_the_evening_rush_is_the_way_back(self):
        seen = []
        engine = otp.Otp("http://otp.test", mock_otp([600, 600, 600], seen), today=date(2026, 10, 27), valid_to=date(2026, 11, 30))
        engine.minutes(ORIGIN, north(3000), "weekday_rush", "back")
        self.assertEqual([v["dateTime"][11:16] for v in seen], ["17:00", "17:30", "18:00"])

    def test_a_departure_without_an_itinerary_is_skipped_and_none_at_all_is_no_route(self):
        engine = otp.Otp("http://otp.test", mock_otp([None, 900, None]), today=date(2026, 10, 27), valid_to=None)
        self.assertEqual(engine.minutes(ORIGIN, north(1000), "sunday", "out")[0], 15.0)
        engine = otp.Otp("http://otp.test", mock_otp([None, None, None]), today=date(2026, 10, 27), valid_to=None)
        with self.assertRaises(otp.NoRoute):
            engine.minutes(ORIGIN, north(1000), "sunday", "out")
        engine = otp.Otp("http://otp.test", mock_otp(["error"]), today=date(2026, 10, 27), valid_to=None)
        with self.assertRaises(otp.NoRoute):
            engine.minutes(ORIGIN, north(1000), "sunday", "out")

    def test_make_engine_needs_the_url(self):
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_OTP_URL": ""}):
            self.assertIsNone(otp.make_engine())
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_OTP_URL": "http://otp.test"}):
            self.assertEqual(otp.make_engine().url, "http://otp.test")


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class WeeklyWithOtpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {
            "APTSCOUT_DATA_DIR": self.tmp.name, "APTSCOUT_DEV_USER": "alex", "APTSCOUT_NOMINATIM_URL": "",
            "APTSCOUT_VALHALLA_URL": "", "APTSCOUT_OTP_URL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        import aptscout.app as app_module

        self.app = app_module.create_app(web_dist=Path(self.tmp.name) / "none")
        self.client = TestClient(self.app)
        lat, lon = ORIGIN
        self.apt = self.client.post("/api/apartments", json={"address": "1 Fictional Ave", "lat": lat, "lon": lon}).json()["id"]
        job = north(6000)
        self.client.post("/api/destinations", json={
            "name": "Job", "kind": "place", "lat": job[0], "lon": job[1], "trips_per_week": 5, "mode": "transit",
            "time_band": "weekday_rush"})

    def part(self):
        return self.client.get(f"/api/apartments/{self.apt}").json()["weekly"]["destinations"][0]

    def test_otp_times_replace_the_estimate_and_are_cached(self):
        responses = [1200] * 3 + [1800] * 3          # out 20 min, back 30 min
        self.app.state.otp = otp.Otp("http://otp.test", mock_otp(responses), today=date(2026, 10, 27), valid_to=date(2026, 11, 30))
        part = self.part()
        self.assertEqual((part["out"], part["back"], part["round_trip"], part["weekly"]), (20.0, 30.0, 50.0, 250.0))
        self.assertEqual(part["method"], "otp")
        self.assertEqual(self.part()["weekly"], 250.0)   # second read: cache, the mock has no calls left

    def test_an_outage_falls_back_to_the_estimate_and_is_not_cached(self):
        self.app.state.otp = otp.Otp("http://otp.test", mock_otp([httpx.ConnectError("down")] * 2), today=date(2026, 10, 27))
        part = self.part()
        self.assertTrue(part["method"].startswith("estimate:fallback"))
        self.assertIsNotNone(part["weekly"])
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT count(*) FROM travel_time").fetchone()[0], 0)
        conn.close()

    def test_estimate_and_otp_times_do_not_share_a_cache(self):
        self.part()                                       # estimate, cached
        self.app.state.otp = otp.Otp("http://otp.test", mock_otp([600] * 6), today=date(2026, 10, 27))
        self.assertEqual(self.part()["method"], "otp")

    def test_a_new_feed_makes_times_stale_and_recompute_drops_them(self):
        self.part()
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT count(*) FROM travel_time").fetchone()[0], 2)
        conn.close()
        datasets.record("cta_gtfs", valid_to="2026-12-31")   # a feed arrives: its fetch time is the new version
        message = recompute.run()
        conn = db.connect()
        versions = {r[0] for r in conn.execute("SELECT version FROM travel_time")}
        conn.close()
        self.assertEqual(len(versions), 1)
        self.assertIn("recomputed 1 apartments", message)
        self.assertNotIn("none", next(iter(versions)).split("/")[2])


class ClipAndInputsTest(unittest.TestCase):
    def test_clip_keeps_whole_ways_that_touch_the_box(self):
        import osmium

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, dest = Path(tmp.name) / "src.osm.pbf", Path(tmp.name) / "out.osm.pbf"
        M = osmium.osm.mutable
        with osmium.SimpleWriter(str(src)) as w:
            w.add_node(M.Node(id=1, location=(-87.60, 41.00)))      # inside
            w.add_node(M.Node(id=2, location=(-80.00, 41.00)))      # outside, but on a way that enters the box
            w.add_node(M.Node(id=3, location=(-70.00, 10.00)))      # far away
            w.add_node(M.Node(id=4, location=(-70.01, 10.00)))
            w.add_way(M.Way(id=10, nodes=[1, 2], tags={"highway": "residential"}))
            w.add_way(M.Way(id=11, nodes=[3, 4], tags={"highway": "residential"}))
        counts = clip.clip(src, dest, [-88.0, 40.9, -87.5, 41.5])
        self.assertEqual(counts, {"nodes": 2, "ways": 1})
        found = [(o.id, o.is_node()) for o in osmium.FileProcessor(str(dest), osmium.osm.NODE | osmium.osm.WAY)]
        self.assertEqual(sorted(found), [(1, True), (2, True), (10, False)])

    def test_otp_inputs_need_the_downloads_first(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DATA_DIR": tmp.name}):
            with self.assertRaisesRegex(RuntimeError, "fetch-osm"):
                datasets.build_otp_inputs(config.load_city())

    def test_otp_inputs_are_assembled_and_the_graph_age_is_reported(self):
        import osmium

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DATA_DIR": tmp.name}):
            cache = config.cache_dir()
            (cache / "osm").mkdir(parents=True)
            (cache / "cta").mkdir(parents=True)
            with osmium.SimpleWriter(str(cache / "osm" / "extract.osm.pbf")) as w:
                w.add_node(osmium.osm.mutable.Node(id=1, location=(-87.6, 41.9)))
            (cache / "cta" / "google_transit.zip").write_bytes(b"zip")
            datasets.record("cta_gtfs", valid_to="2099-01-01")
            datasets.build_otp_inputs(config.load_city())
            self.assertEqual(sorted(p.name for p in (cache / "otp").iterdir()), ["build-config.json", "cta-gtfs.zip", "streets.osm.pbf"])
            self.assertEqual(json.loads((cache / "otp" / "build-config.json").read_text())["transitModelTimeZone"], "America/Chicago")
            self.assertEqual(datasets.status()["cta_gtfs"]["status"], "ok")
            self.assertEqual(datasets.status()["otp_inputs"]["status"], "ok")
            datasets.record("cta_gtfs", valid_to="2099-01-01")    # a newer feed arrives
            self.assertEqual(datasets.status()["otp_inputs"]["status"], "older than the CTA feed")


if __name__ == "__main__":
    unittest.main()
