"""Backup and restore, the job schedule, export and import: the owner's data survives."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from aptscout import backup, db, export_api, importer, jobs  # noqa: E402


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


class RetentionTest(unittest.TestCase):
    def test_keeps_the_newest_of_each_recent_day_and_of_each_older_month(self):
        stamps = [at("2026-10-27 03:00"), at("2026-10-27 15:00"), at("2026-10-26 03:00"), at("2026-10-01 03:00"),
                  at("2026-09-30 03:00"), at("2026-09-15 03:00"), at("2026-09-02 03:00"), at("2026-03-05 03:00"),
                  at("2026-04-05 03:00"), at("2026-05-05 03:00"), at("2026-06-05 03:00"), at("2026-07-05 03:00"),
                  at("2026-08-05 03:00"), at("2025-01-01 03:00")]
        keep = backup.to_keep(stamps, at("2026-10-27 20:00"))
        self.assertIn(at("2026-10-27 15:00"), keep)
        self.assertNotIn(at("2026-10-27 03:00"), keep)          # an older copy of the same day
        self.assertIn(at("2026-10-26 03:00"), keep)
        self.assertIn(at("2026-10-01 03:00"), keep)             # October's newest outside the 14 days
        self.assertIn(at("2026-09-30 03:00"), keep)             # newest of September
        self.assertNotIn(at("2026-09-15 03:00"), keep)
        self.assertNotIn(at("2026-04-05 03:00"), keep)          # beyond the six months (Oct to May)
        self.assertNotIn(at("2026-03-05 03:00"), keep)
        self.assertNotIn(at("2025-01-01 03:00"), keep)
        self.assertIn(at("2026-05-05 03:00"), keep)


class DataDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.backups = Path(self.tmp.name) / "backups"
        patcher = unittest.mock.patch.dict(os.environ, {
            "APTSCOUT_DATA_DIR": str(self.data), "APTSCOUT_BACKUP_DIR": str(self.backups), "APTSCOUT_DEV_USER": "alex",
            "APTSCOUT_VALHALLA_URL": "", "APTSCOUT_OTP_URL": "", "APTSCOUT_NOMINATIM_URL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)


class BackupTest(DataDirTestCase):
    def make_db(self, note):
        conn = db.connect()
        conn.execute("INSERT OR IGNORE INTO app_user (subject, name) VALUES ('alex', 'alex')")
        uid = conn.execute("SELECT id FROM app_user").fetchone()[0]
        conn.execute("INSERT INTO apartment (owner_id, address, notes, created, updated) VALUES (?, '1 Fictional Ave', ?, 't', 't')", (uid, note))
        conn.commit()
        conn.close()

    def test_backup_restore_round_trip_with_photos(self):
        self.make_db("sunny")
        (self.data / "photos" / "1").mkdir(parents=True)
        (self.data / "photos" / "1" / "a.jpg").write_bytes(b"jpeg-a")
        message = backup.run(at("2026-10-27 03:00"))
        self.assertIn("1 new photos", message)
        copy = self.backups / "aptscout-20261027-030000.sqlite"
        self.assertTrue(copy.exists())
        self.assertEqual(backup.run(at("2026-10-27 15:00")).count("0 new photos"), 1)   # second run copies nothing new
        # disaster: the database changes and a photo is lost
        conn = db.connect()
        conn.execute("UPDATE apartment SET notes = 'wrecked'")
        conn.commit()
        conn.close()
        (self.data / "photos" / "1" / "a.jpg").unlink()
        backup.restore("aptscout-20261027-150000.sqlite")
        conn = sqlite3.connect(db.db_path())
        self.assertEqual(conn.execute("SELECT notes FROM apartment").fetchone()[0], "sunny")
        conn.close()
        self.assertEqual((self.data / "photos" / "1" / "a.jpg").read_bytes(), b"jpeg-a")
        self.assertEqual(len(list(self.data.glob("aptscout.sqlite.before-restore-*"))), 1)

    def test_old_copies_are_pruned_and_a_bad_backup_is_refused(self):
        self.make_db("x")
        for day in ("2026-10-20 03:00", "2026-10-20 15:00", "2026-10-21 03:00"):
            backup.run(at(day))
        left = sorted(p.name for p in self.backups.glob("aptscout-*.sqlite"))
        self.assertEqual(left, ["aptscout-20261020-150000.sqlite", "aptscout-20261021-030000.sqlite"])
        broken = self.backups / "aptscout-20261022-030000.sqlite"
        broken.write_bytes(b"this is not a database" * 100)
        with self.assertRaises(Exception):
            backup.restore(broken.name)
        conn = db.connect()      # the live database was not touched
        self.assertEqual(conn.execute("SELECT notes FROM apartment").fetchone()[0], "x")
        conn.close()

    def test_nothing_is_written_without_a_destination(self):
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_BACKUP_DIR": ""}):
            with self.assertRaisesRegex(RuntimeError, "owner chooses"):
                backup.run()


class JobsTest(unittest.TestCase):
    def test_what_is_due(self):
        now = at("2026-10-27 12:00")
        self.assertEqual(jobs.due({}, now), ["backup", "gtfs", "osm"])
        runs = {"backup": "2026-10-27 03:00".replace(" ", "T") + ":00", "gtfs": "2026-10-19T03:00:00", "osm": "2026-10-01T03:00:00"}
        self.assertEqual(jobs.due(runs, now), ["gtfs"])
        runs["gtfs"] = "2026-10-26T12:00:00"
        runs["backup"] = "2026-10-26T11:00:00"
        self.assertEqual(jobs.due(runs, now), ["backup"])


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class ExportImportTest(DataDirTestCase):
    def client_for(self, data_dir=None):
        import aptscout.app as app_module

        if data_dir:
            os.environ["APTSCOUT_DATA_DIR"] = str(data_dir)
        return TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none"))

    def fill(self, c):
        conn = db.connect()
        importer.upsert(conn, "osm", [importer.Imported("osm:n1", "grocery", "Fictional Foods", 41.9, -87.65, "osm"),
                                      importer.Imported("osm:n2", "lap_pool", "Test Natatorium", 41.91, -87.65, "osm", lap_score="likely")])
        conn.close()
        c.post("/api/apartments", json={"address": "1 Fictional Ave", "lat": 41.9, "lon": -87.65, "rent": 1800, "facing": ["S"], "notes": "=cmd|' /C calc'!A0"})
        c.patch("/api/apartments/1", json={"status": "toured"})
        c.post("/api/destinations", json={"name": "Groceries", "kind": "category", "category_key": "grocery", "trips_per_week": 2})
        c.post("/api/categories", json={"name": "Climbing gym", "colour": "#aa3300"})
        c.post("/api/places", json={"category": "u-climbing-gym", "name": "My Wall", "lat": 41.95, "lon": -87.7})
        pool = next(f for f in c.get("/api/places").json()["features"] if f["properties"]["category"] == "lap_pool")
        c.patch(f"/api/places/{pool['properties']['id']}", json={"state": "confirmed", "favourite": True, "notes": "25 m"})
        c.patch("/api/categories/grocery", json={"weight": 9})
        c.put("/api/settings", json={"combined_on": True, "w_time": 7})

    def normalise(self, data):
        data = json.loads(json.dumps(data))
        data.pop("exported")
        return data

    def test_round_trip_into_a_fresh_install(self):
        c = self.client_for()
        self.fill(c)
        exported = c.get("/api/export").json()
        self.assertEqual(exported["marks"][0]["ext_id"], "osm:n2")
        self.assertEqual(exported["apartments"][0]["status_history"][-1]["status"], "toured")
        fresh = Path(self.tmp.name) / "fresh"
        c2 = self.client_for(fresh)
        conn = db.connect()      # the fresh install has the same public data (re-imported places)
        importer.upsert(conn, "osm", [importer.Imported("osm:n1", "grocery", "Fictional Foods", 41.9, -87.65, "osm"),
                                      importer.Imported("osm:n2", "lap_pool", "Test Natatorium", 41.91, -87.65, "osm", lap_score="likely")])
        conn.close()
        self.assertEqual(c2.post("/api/import", json=exported).status_code, 409)       # needs ?replace=true
        done = c2.post("/api/import?replace=true", json=exported)
        self.assertEqual(done.json(), {"apartments": 1, "destinations": 1, "places": 1, "marks_skipped": 0})
        again = c2.get("/api/export").json()
        self.assertEqual(self.normalise(again), self.normalise(exported))
        # and importing twice does not double anything
        c2.post("/api/import?replace=true", json=exported)
        self.assertEqual(len(c2.get("/api/apartments").json()), 1)

    def test_bad_imports_change_nothing(self):
        c = self.client_for()
        self.fill(c)
        for bad in ({"aptscout_export": 99}, {"aptscout_export": 1, "apartments": [{"rent": -5}]},
                    {"aptscout_export": 1, "places": [{"category_key": "nope", "name": "x", "lat": 1, "lon": 1}]}):
            self.assertEqual(c.post("/api/import?replace=true", json=bad).status_code, 422, bad)
        self.assertEqual(len(c.get("/api/apartments").json()), 1)

    def test_csv_defuses_formulas(self):
        c = self.client_for()
        self.fill(c)
        resp = c.get("/api/export.csv")
        self.assertIn("attachment", resp.headers["content-disposition"])
        lines = resp.text.strip().splitlines()
        self.assertTrue(lines[0].startswith("label,address"))
        self.assertIn("'=cmd", lines[1])
        self.assertEqual(export_api.csv_safe("-1+1"), "'-1+1")
        self.assertEqual(export_api.csv_safe(1800), "1800")


if __name__ == "__main__":
    unittest.main()
