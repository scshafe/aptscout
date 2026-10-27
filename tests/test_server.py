"""Server tests on a synthetic GTFS feed: made-up lines, stops and addresses."""

import importlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:  # run through scripts/verify, which installs the server's requirements
    TestClient = None

from aptscout import datasets, gtfs  # noqa: E402

ROUTES = (
    "route_id,route_short_name,route_long_name,route_type,route_color\n"
    "R1,Teal,Teal Line,1,00AAAA\n"
    "B9,9,Nine Street,3,\n"
)
TRIPS = (
    "route_id,service_id,trip_id,direction_id,shape_id\n"
    "R1,S,t1,0,sh_r1\nR1,S,t2,0,sh_r1\nR1,S,t3,1,sh_r1_short\n"
    "B9,S,t4,0,sh_b9\n"
)
# sh_r1_short carries 1 of 3 trips (>= 25%), so it is kept as a branch.
SHAPES = (
    "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
    "sh_r1,41.0000,-87.6000,1\nsh_r1,41.0001,-87.6000,2\nsh_r1,41.0100,-87.6000,3\n"
    "sh_r1_short,41.0000,-87.6000,1\nsh_r1_short,41.0050,-87.6000,2\n"
    "sh_b9,41.0000,-87.6100,2\nsh_b9,41.0000,-87.6200,3\nsh_b9,41.0000,-87.6050,1\n"
)
STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
    "100,Main & First,41.0000,-87.6050,0,\n"
    "40001,Teal Central,41.0050,-87.6000,1,\n"
    "30001,Teal Central platform,41.0050,-87.6000,0,40001\n"
)
CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    "S,1,1,1,1,1,0,0,20260101,20261130\n"
)


def make_feed(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("routes.txt", ROUTES)
        zf.writestr("trips.txt", TRIPS)
        zf.writestr("shapes.txt", SHAPES)
        zf.writestr("stops.txt", STOPS)
        zf.writestr("calendar.txt", CALENDAR)


class GtfsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zip = Path(self.tmp.name) / "feed.zip"
        make_feed(self.zip)

    def test_parse(self):
        with zipfile.ZipFile(self.zip) as zf:
            parsed = gtfs.parse(zf)
        rail, bus = parsed["rail"]["features"], parsed["bus"]["features"]
        self.assertEqual(len(rail), 2)  # main shape and the branch
        self.assertEqual(rail[0]["properties"]["color"], "#00AAAA")
        self.assertEqual(len(bus), 1)
        self.assertEqual(bus[0]["properties"]["color"], "#666666")  # no colour given
        # shape points are ordered by sequence, not by file order
        self.assertEqual(bus[0]["geometry"]["coordinates"][0], [-87.605, 41.0])
        # the 11 m step is thinned out; the ends are kept
        main = max(rail, key=lambda f: len(f["geometry"]["coordinates"]))
        self.assertEqual(len(main["geometry"]["coordinates"]), 2)
        kinds = {f["properties"]["id"]: f["properties"]["kind"] for f in parsed["stops"]["features"]}
        self.assertEqual(kinds, {"100": "bus", "40001": "rail"})  # the platform is skipped
        self.assertEqual(parsed["meta"]["valid_to"], "2026-11-30")

    def test_feed_status(self):
        today = date(2026, 11, 20)
        self.assertEqual(datasets.feed_status("2026-12-31", today), "ok")
        self.assertEqual(datasets.feed_status("2026-11-30", today), "expiring")
        self.assertEqual(datasets.feed_status("2026-11-19", today), "expired")
        self.assertEqual(datasets.feed_status(None, today), "unknown")

    def test_extract_command(self):
        cmd = datasets.extract_command("pmtiles", "https://example.test/b.pmtiles", Path("out"), [-1.5, 2, 3, 4.5])
        self.assertEqual(cmd[1:3], ["extract", "https://example.test/b.pmtiles"])
        self.assertEqual(cmd[-1], "--bbox=-1.5,2,3,4.5")


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name) / "data"
        make_feed(Path(self.tmp.name) / "feed.zip")
        env = {"APTSCOUT_DATA_DIR": str(data)}
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        gtfs.write(Path(self.tmp.name) / "feed.zip", data / "cache" / "cta")
        tiles = data / "cache" / "tiles"
        tiles.mkdir(parents=True)
        (tiles / "city.pmtiles").write_bytes(bytes(range(256)))
        import aptscout.app as app_module

        self.client = TestClient(importlib.reload(app_module).create_app(web_dist=Path(self.tmp.name) / "none"))

    def test_health_is_open(self):
        self.assertEqual(self.client.get("/healthz").json(), {"ok": True})

    def test_api_needs_sign_in(self):
        self.assertEqual(self.client.get("/api/cta/rail").status_code, 401)
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": "tester"}):
            self.assertEqual(self.client.get("/api/me").json(), {"user": "tester"})
            rail = self.client.get("/api/cta/rail").json()
            self.assertEqual(len(rail["features"]), 2)
            self.assertEqual(self.client.get("/api/cta/nope").status_code, 404)
            self.assertTrue(self.client.get("/api/config").json()["tiles"])

    def test_tiles_serve_byte_ranges(self):
        resp = self.client.get("/tiles/city.pmtiles", headers={"Range": "bytes=10-19", "Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.content, bytes(range(10, 20)))
        self.assertNotIn("content-encoding", resp.headers)


import unittest.mock  # noqa: E402  (used by the classes above)

if __name__ == "__main__":
    unittest.main()
