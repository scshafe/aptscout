"""Photo upload, access and clean-up, with tiny made-up JPEG bytes."""

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

JPEG = b"\xff\xd8\xff\xe0" + b"fictional photo bytes" * 10


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class PhotosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {
            "APTSCOUT_DATA_DIR": self.tmp.name, "APTSCOUT_DEV_USER": "alex"})
        patcher.start()
        self.addCleanup(patcher.stop)
        import aptscout.app as app_module

        self.client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none"))
        self.apt = self.client.post("/api/apartments", json={"address": "1 Fictional Ave"}).json()["id"]

    def upload(self, data=JPEG, apt=None):
        return self.client.post(f"/api/apartments/{apt or self.apt}/photos", content=data, headers={"Content-Type": "image/jpeg"})

    def test_upload_list_fetch_caption_delete(self):
        made = self.upload()
        self.assertEqual(made.status_code, 201)
        pid = made.json()["id"]
        self.assertEqual([p["id"] for p in self.client.get(f"/api/apartments/{self.apt}/photos").json()], [pid])
        got = self.client.get(f"/api/photos/{pid}")
        self.assertEqual((got.status_code, got.content, got.headers["content-type"]), (200, JPEG, "image/jpeg"))
        self.assertEqual(self.client.patch(f"/api/photos/{pid}", json={"caption": "kitchen"}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/apartments/{self.apt}/photos").json()[0]["caption"], "kitchen")
        files = list((Path(self.tmp.name) / "photos" / str(self.apt)).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(self.client.delete(f"/api/photos/{pid}").status_code, 204)
        self.assertFalse(files[0].exists())
        self.assertEqual(self.client.get(f"/api/photos/{pid}").status_code, 404)

    def test_rejects_other_files_and_big_ones(self):
        self.assertEqual(self.upload(b"GIF89a....").status_code, 415)
        self.assertEqual(self.upload(JPEG + b"x" * (4 * 1024 * 1024)).status_code, 413)

    def test_other_owners_cannot_see_or_add(self):
        pid = self.upload().json()["id"]
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_DEV_USER": "sam"}):
            self.assertEqual(self.client.get(f"/api/photos/{pid}").status_code, 404)
            self.assertEqual(self.client.delete(f"/api/photos/{pid}").status_code, 404)
            self.assertEqual(self.upload().status_code, 404)
            self.assertEqual(self.client.get(f"/api/apartments/{self.apt}/photos").status_code, 404)

    def test_deleting_the_apartment_removes_its_files(self):
        self.upload()
        folder = Path(self.tmp.name) / "photos" / str(self.apt)
        self.assertTrue(folder.exists())
        self.client.delete(f"/api/apartments/{self.apt}")
        self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
