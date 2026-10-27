"""Sign-in with Pocket ID (OpenID Connect, authorization code flow with PKCE; design section 9).

Configured by environment: APTSCOUT_OIDC_ISSUER, APTSCOUT_OIDC_CLIENT_ID,
APTSCOUT_OIDC_CLIENT_SECRET, APTSCOUT_PUBLIC_URL (https://aptscout.<tailnet>.ts.net)
and APTSCOUT_SESSION_SECRET (random, 32 bytes or more). With none of them set the
development stub (APTSCOUT_DEV_USER) applies; once OIDC is configured the stub is
ignored, so a stray variable cannot open a deployed app.

The ID token comes straight from the token endpoint over TLS, which OpenID Connect
Core (3.1.3.7) allows to be trusted without checking its signature; its issuer,
audience, expiry and nonce are checked.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

SESSION_COOKIE = "aptscout_session"
LOGIN_COOKIE = "aptscout_login"
SESSION_SECONDS = 14 * 24 * 3600
LOGIN_SECONDS = 600
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Settings:
    def __init__(self, env=os.environ):
        self.issuer = (env.get("APTSCOUT_OIDC_ISSUER") or "").rstrip("/")
        self.client_id = env.get("APTSCOUT_OIDC_CLIENT_ID") or ""
        self.client_secret = env.get("APTSCOUT_OIDC_CLIENT_SECRET") or ""
        self.public_url = (env.get("APTSCOUT_PUBLIC_URL") or "").rstrip("/")
        self.secret = (env.get("APTSCOUT_SESSION_SECRET") or "").encode()
        self.allowed = {s for s in (env.get("APTSCOUT_ALLOWED_SUBJECTS") or "").split(",") if s}
        self.enabled = bool(self.issuer)
        if self.enabled:
            missing = [n for n, v in (("CLIENT_ID", self.client_id), ("CLIENT_SECRET", self.client_secret),
                                      ("PUBLIC_URL", self.public_url), ("SESSION_SECRET", self.secret)) if not v]
            if missing:
                raise RuntimeError("OIDC is configured but APTSCOUT_" + ", APTSCOUT_".join(missing) + " is missing")
            if len(self.secret) < 32:
                raise RuntimeError("APTSCOUT_SESSION_SECRET must be at least 32 characters")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


def sign(settings: Settings, payload: dict) -> str:
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = b64(hmac.new(settings.secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def unsign(settings: Settings, token: str | None) -> dict | None:
    """The payload of a token we signed and that has not expired, else None."""
    if not token or "." not in token:
        return None
    body, mac = token.rsplit(".", 1)
    good = b64(hmac.new(settings.secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, good):
        return None
    try:
        payload = json.loads(unb64(body))
    except ValueError:
        return None
    return payload if payload.get("exp", 0) > time.time() else None


def id_token_claims(token: str) -> dict:
    try:
        return json.loads(unb64(token.split(".")[1]))
    except (IndexError, ValueError):
        raise HTTPException(400, "malformed ID token")


def check_claims(settings: Settings, claims: dict, nonce: str, now: float | None = None) -> None:
    now = now or time.time()
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if claims.get("iss", "").rstrip("/") != settings.issuer:
        raise HTTPException(400, "wrong issuer")
    if settings.client_id not in audiences:
        raise HTTPException(400, "wrong audience")
    if claims.get("exp", 0) <= now:
        raise HTTPException(400, "ID token expired")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise HTTPException(400, "wrong nonce")
    if not claims.get("sub"):
        raise HTTPException(400, "no subject")


def build_router(settings: Settings, client_factory=lambda: httpx.Client(timeout=15)) -> APIRouter:
    router = APIRouter(prefix="/auth")

    def discover(client) -> dict:
        resp = client.get(settings.issuer + "/.well-known/openid-configuration")
        resp.raise_for_status()
        return resp.json()

    @router.get("/login")
    def login():
        if not settings.enabled:
            raise HTTPException(404)
        with client_factory() as client:
            meta = discover(client)
        state, nonce, verifier = (secrets.token_urlsafe(24) for _ in range(3))
        challenge = b64(hashlib.sha256(verifier.encode()).digest())
        query = urlencode({
            "response_type": "code", "client_id": settings.client_id, "scope": "openid profile",
            "redirect_uri": settings.public_url + "/auth/callback", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        response = RedirectResponse(meta["authorization_endpoint"] + "?" + query, status_code=302)
        response.set_cookie(LOGIN_COOKIE, sign(settings, {"s": state, "n": nonce, "v": verifier, "exp": time.time() + LOGIN_SECONDS}),
                            max_age=LOGIN_SECONDS, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/auth")
        return response

    @router.get("/callback")
    def callback(request: Request, code: str = "", state: str = ""):
        if not settings.enabled:
            raise HTTPException(404)
        login_data = unsign(settings, request.cookies.get(LOGIN_COOKIE))
        if not login_data or not code or not hmac.compare_digest(login_data["s"], state):
            raise HTTPException(400, "sign-in expired or did not match; start again")
        with client_factory() as client:
            meta = discover(client)
            resp = client.post(meta["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": settings.public_url + "/auth/callback",
                "client_id": settings.client_id, "client_secret": settings.client_secret,
                "code_verifier": login_data["v"]})
        if resp.status_code != 200:
            raise HTTPException(400, "the sign-in server refused the code")
        claims = id_token_claims(resp.json().get("id_token", ""))
        check_claims(settings, claims, login_data["n"])
        if settings.allowed and claims["sub"] not in settings.allowed:
            raise HTTPException(403, "this account may not use aptscout")
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(SESSION_COOKIE, sign(settings, {"sub": claims["sub"], "name": claims.get("name") or claims.get("preferred_username") or "",
                                                          "exp": time.time() + SESSION_SECONDS}),
                            max_age=SESSION_SECONDS, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
        response.delete_cookie(LOGIN_COOKIE, path="/auth")
        return response

    @router.post("/logout")
    def logout():
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return router


def origin_ok(settings: Settings, request: Request) -> bool:
    """Reject cross-site writes: an unsafe request that names an origin must name ours."""
    if request.method not in UNSAFE:
        return True
    origin = request.headers.get("origin")
    return origin is None or origin == settings.public_url


def user_dependency(settings: Settings):
    """The FastAPI dependency naming the signed-in user (the OIDC subject, or the dev stub)."""

    def current_user(request: Request) -> str:
        if settings.enabled:
            session = unsign(settings, request.cookies.get(SESSION_COOKIE))
            if not session:
                raise HTTPException(status_code=401, detail="not signed in")
            return session["sub"]
        user = os.environ.get("APTSCOUT_DEV_USER")
        if not user:
            raise HTTPException(status_code=401, detail="not signed in")
        return user

    return current_user
