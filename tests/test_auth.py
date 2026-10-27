"""Pocket ID sign-in against a pretend OpenID provider."""

import base64
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from aptscout import auth  # noqa: E402

ISSUER = "https://id.example.test"
PUBLIC = "https://aptscout.example.test"
ENV = {
    "APTSCOUT_OIDC_ISSUER": ISSUER, "APTSCOUT_OIDC_CLIENT_ID": "client-1", "APTSCOUT_OIDC_CLIENT_SECRET": "shh",
    "APTSCOUT_PUBLIC_URL": PUBLIC, "APTSCOUT_SESSION_SECRET": "x" * 40,
}


def jwt(claims: dict) -> str:
    part = lambda d: auth.b64(json.dumps(d).encode())
    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


class Provider:
    """Answers discovery and the token endpoint; remembers what it was sent."""

    def __init__(self):
        self.token_form = None
        self.claims = {}
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"authorization_endpoint": ISSUER + "/authorize", "token_endpoint": ISSUER + "/token"})
        self.token_form = parse_qs(request.content.decode())
        return httpx.Response(self.status, json={"id_token": jwt(self.claims)})


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class SignInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {**ENV, "APTSCOUT_DATA_DIR": self.tmp.name, "APTSCOUT_DEV_USER": "stub-user"}
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = Provider()
        import aptscout.app as app_module

        self.client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none", oidc_client_factory=self.factory),
                                 base_url=PUBLIC, follow_redirects=False)

    def factory(self):
        return httpx.Client(transport=httpx.MockTransport(self.provider.handler))

    def start(self):
        resp = self.client.get("/auth/login")
        self.assertEqual(resp.status_code, 302)
        query = parse_qs(urlparse(resp.headers["location"]).query)
        return resp, query

    def claims(self, query, **over):
        return {"iss": ISSUER, "aud": "client-1", "exp": time.time() + 600, "nonce": query["nonce"][0],
                "sub": "user-1", "name": "Alex Tester", **over}

    def test_the_stub_is_ignored_once_oidc_is_configured(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_full_sign_in(self):
        resp, query = self.start()
        self.assertEqual(urlparse(resp.headers["location"]).path, "/authorize")
        self.assertEqual((query["client_id"], query["code_challenge_method"], query["response_type"]),
                         (["client-1"], ["S256"], ["code"]))
        self.assertEqual(query["redirect_uri"], [PUBLIC + "/auth/callback"])
        self.assertIn("HttpOnly", resp.headers["set-cookie"])
        self.provider.claims = self.claims(query)
        done = self.client.get("/auth/callback", params={"code": "abc", "state": query["state"][0]})
        self.assertEqual((done.status_code, done.headers["location"]), (302, "/"))
        form = self.provider.token_form
        self.assertEqual((form["code"], form["client_secret"], form["grant_type"]), (["abc"], ["shh"], ["authorization_code"]))
        self.assertTrue(form["code_verifier"][0])
        set_cookie = " ".join(done.headers.get_list("set-cookie"))
        self.assertIn("aptscout_session=", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertEqual(self.client.get("/api/me").json(), {"user": "user-1"})

    def test_bad_callbacks_are_refused(self):
        _, query = self.start()
        good_state = query["state"][0]
        cases = {
            "wrong state": ({}, "other-state"),
            "wrong issuer": ({"iss": "https://evil.example.test"}, good_state),
            "wrong audience": ({"aud": "someone-else"}, good_state),
            "expired": ({"exp": time.time() - 5}, good_state),
            "wrong nonce": ({"nonce": "nope"}, good_state),
            "no subject": ({"sub": ""}, good_state),
        }
        for name, (over, state) in cases.items():
            self.provider.claims = self.claims(query, **over)
            resp = self.client.get("/auth/callback", params={"code": "abc", "state": state})
            self.assertEqual(resp.status_code, 400, name)
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_callback_without_a_login_cookie_or_with_a_refused_code(self):
        self.assertEqual(self.client.get("/auth/callback", params={"code": "a", "state": "b"}).status_code, 400)
        _, query = self.start()
        self.provider.status = 400
        resp = self.client.get("/auth/callback", params={"code": "abc", "state": query["state"][0]})
        self.assertEqual(resp.status_code, 400)

    def test_session_cookies_cannot_be_forged_or_outlive_their_time(self):
        settings = auth.Settings(ENV)
        token = auth.sign(settings, {"sub": "user-1", "exp": time.time() + 60})
        self.assertEqual(auth.unsign(settings, token)["sub"], "user-1")
        body, mac = token.rsplit(".", 1)
        forged = auth.b64(json.dumps({"sub": "admin", "exp": time.time() + 60}).encode()) + "." + mac
        self.assertIsNone(auth.unsign(settings, forged))
        self.assertIsNone(auth.unsign(settings, auth.sign(settings, {"sub": "u", "exp": time.time() - 1})))
        self.assertIsNone(auth.unsign(auth.Settings({**ENV, "APTSCOUT_SESSION_SECRET": "y" * 40}), token))
        self.assertIsNone(auth.unsign(settings, "garbage"))
        self.client.cookies.set("aptscout_session", forged)
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_only_allowed_subjects_get_in(self):
        with unittest.mock.patch.dict(os.environ, {"APTSCOUT_ALLOWED_SUBJECTS": "someone-else"}):
            import aptscout.app as app_module

            client = TestClient(app_module.create_app(web_dist=Path(self.tmp.name) / "none", oidc_client_factory=self.factory),
                                base_url=PUBLIC, follow_redirects=False)
            query = parse_qs(urlparse(client.get("/auth/login").headers["location"]).query)
            self.provider.claims = self.claims(query)
            resp = client.get("/auth/callback", params={"code": "abc", "state": query["state"][0]})
            self.assertEqual(resp.status_code, 403)

    def test_cross_site_writes_are_refused(self):
        settings = auth.Settings(ENV)
        cookie = auth.sign(settings, {"sub": "user-1", "exp": time.time() + 60})
        self.client.cookies.set("aptscout_session", cookie)
        body = {"address": "1 Fictional Ave"}
        evil = self.client.post("/api/apartments", json=body, headers={"Origin": "https://evil.example.test"})
        self.assertEqual(evil.status_code, 403)
        mine = self.client.post("/api/apartments", json=body, headers={"Origin": PUBLIC})
        self.assertEqual(mine.status_code, 201)
        self.assertEqual(self.client.post("/api/apartments", json=body).status_code, 201)   # no Origin: same-site tools
        self.assertEqual(self.client.get("/api/apartments", headers={"Origin": "https://evil.example.test"}).status_code, 200)

    def test_logout_clears_the_session(self):
        out = self.client.post("/auth/logout", headers={"Origin": PUBLIC})
        self.assertEqual(out.status_code, 303)
        self.assertIn("aptscout_session=", out.headers["set-cookie"])


class ConfigTest(unittest.TestCase):
    def test_partial_or_weak_configuration_fails_loudly(self):
        with self.assertRaisesRegex(RuntimeError, "CLIENT_SECRET"):
            auth.Settings({**ENV, "APTSCOUT_OIDC_CLIENT_SECRET": ""})
        with self.assertRaisesRegex(RuntimeError, "at least 32"):
            auth.Settings({**ENV, "APTSCOUT_SESSION_SECRET": "short"})
        self.assertFalse(auth.Settings({}).enabled)


if __name__ == "__main__":
    unittest.main()
