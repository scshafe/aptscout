"""The aptscout HTTP app (design sections 2, 9, 14).

M1 serves the basemap tiles, the basemap assets, the CTA overlays and the
built web app. Sign-in is a development stub until Pocket ID (M7): the user
comes from APTSCOUT_DEV_USER, and /api/* answers 401 when it is unset.
"""

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import apartments_api, config, destinations_api, datasets, otp, places_api, routing

OVERLAYS = ("rail", "bus", "stops")


class _GzipExceptTiles(GZipMiddleware):
    """Compress API and static responses, never the tiles: PMTiles reads byte ranges."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/tiles/"):
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


def current_user() -> str:
    user = os.environ.get("APTSCOUT_DEV_USER")
    if not user:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


def create_app(web_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="aptscout", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_GzipExceptTiles, minimum_size=1024)
    city = config.load_city()

    app.state.router = routing.make_router()
    app.state.otp = otp.make_engine()
    app.include_router(places_api.build_router(current_user))
    app.include_router(apartments_api.build_router(current_user))
    app.include_router(destinations_api.build_router(current_user))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/me")
    def me(user: str = Depends(current_user)):
        return {"user": user}

    @app.get("/api/config")
    def map_config(user: str = Depends(current_user)):
        have_tiles = (config.cache_dir() / "tiles" / "city.pmtiles").exists()
        return {
            "city": city["name"], "center": city["center"], "zoom": city["zoom"],
            "bbox": city["bbox"], "tiles": have_tiles,
        }

    @app.get("/api/datasets")
    def dataset_versions(user: str = Depends(current_user)):
        return datasets.status()

    @app.get("/api/cta/{overlay}")
    def cta_overlay(overlay: str, user: str = Depends(current_user)):
        if overlay not in OVERLAYS:
            raise HTTPException(status_code=404)
        path = config.cache_dir() / "cta" / f"{overlay}.geojson"
        if not path.exists():
            raise HTTPException(status_code=404, detail="CTA data not imported; run fetch-gtfs")
        return FileResponse(path, media_type="application/geo+json")

    @app.get("/tiles/city.pmtiles")
    def tiles():
        path = config.cache_dir() / "tiles" / "city.pmtiles"
        if not path.exists():
            raise HTTPException(status_code=404, detail="tiles not built; run build-tiles")
        return FileResponse(path, media_type="application/octet-stream")  # honours Range

    assets = config.cache_dir() / "basemap-assets"
    if assets.is_dir():
        app.mount("/basemap-assets", StaticFiles(directory=assets), name="basemap-assets")

    dist = web_dist if web_dist is not None else Path(os.environ.get("APTSCOUT_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
