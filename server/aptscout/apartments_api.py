"""Apartments, their scores and the address search (design sections 6, 7, 8)."""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from . import config, geocode, scoring
from .places_api import make_deps

STATUSES = ("interested", "contacted", "toured", "applied", "rejected", "signed")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
LOCATION_SOURCES = ("none", "geocoder", "manual")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApartmentIn(BaseModel):
    label: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=40)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    location_source: str | None = None
    rent: int | None = Field(default=None, ge=0, le=100000)
    rent_includes: str = Field(default="", max_length=120)
    fees: int | None = Field(default=None, ge=0, le=100000)
    deposit: int | None = Field(default=None, ge=0, le=100000)
    beds: float | None = Field(default=None, ge=0, le=20)
    baths: float | None = Field(default=None, ge=0, le=20)
    sqft: int | None = Field(default=None, ge=0, le=100000)
    floor: int | None = Field(default=None, ge=-5, le=200)
    floors_in_building: int | None = Field(default=None, ge=1, le=200)
    facing: list[str] = Field(default_factory=list)
    lease_months: int | None = Field(default=None, ge=0, le=120)
    available_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    pets: str = Field(default="", max_length=120)
    laundry: str = Field(default="", max_length=120)
    parking: str = Field(default="", max_length=120)
    listing_url: str = Field(default="", max_length=500)
    status: str = "interested"
    notes: str = Field(default="", max_length=5000)

    @field_validator("facing")
    @classmethod
    def _facing(cls, value):
        bad = [v for v in value if v not in COMPASS]
        if bad:
            raise ValueError(f"facing must be from {COMPASS}")
        return [c for c in COMPASS if c in value]

    @field_validator("status")
    @classmethod
    def _status(cls, value):
        if value not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        return value

    @field_validator("listing_url")
    @classmethod
    def _url(cls, value):
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("the listing link must start with http:// or https://")
        return value


def row_to_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["facing"] = [f for f in out["facing"].split(",") if f]
    del out["owner_id"]
    return out


def build_router(current_user) -> APIRouter:
    router = APIRouter(prefix="/api")
    me = make_deps(current_user)

    def own(conn, uid, apartment_id) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM apartment WHERE id = ? AND owner_id = ?", (apartment_id, uid)).fetchone()
        if row is None:
            raise HTTPException(404)
        return row

    def location(values: dict) -> dict:
        """A pin needs both coordinates; setting one implies a source."""
        if (values.get("lat") is None) != (values.get("lon") is None):
            raise HTTPException(422, "lat and lon go together")
        if values.get("lat") is not None and values.get("location_source") in (None, "none"):
            values["location_source"] = "manual"
        if values.get("location_source") not in (None, *LOCATION_SOURCES):
            raise HTTPException(422, f"location_source must be one of {LOCATION_SOURCES}")
        return values

    @router.get("/apartments")
    def list_apartments(request: Request, ctx=Depends(me)):
        conn, uid = ctx
        out = []
        for row in conn.execute("SELECT * FROM apartment WHERE owner_id = ? ORDER BY id", (uid,)).fetchall():
            item = row_to_dict(row)
            result = scoring.score_apartment(conn, uid, row, request.app.state.router)
            item["place_score"] = result["place_score"]
            item["minutes"] = {c["key"]: c["minutes"] for c in result["categories"]}
            out.append(item)
        return out

    @router.post("/apartments", status_code=201)
    def add_apartment(body: ApartmentIn, ctx=Depends(me)):
        conn, uid = ctx
        values = location(body.model_dump())
        values["facing"] = ",".join(values["facing"])
        values.setdefault("location_source", "none")
        values["location_source"] = values["location_source"] or "none"
        stamp = now()
        cols = ", ".join(values)
        marks = ", ".join("?" * len(values))
        with conn:
            cur = conn.execute(
                f"INSERT INTO apartment (owner_id, created, updated, {cols}) VALUES (?, ?, ?, {marks})",
                (uid, stamp, stamp, *values.values()),
            )
            conn.execute("INSERT INTO apartment_status (apartment_id, status, at) VALUES (?,?,?)",
                         (cur.lastrowid, values["status"], stamp))
        return {"id": cur.lastrowid}

    @router.get("/apartments/{apartment_id}")
    def get_apartment(apartment_id: int, request: Request, ctx=Depends(me)):
        conn, uid = ctx
        row = own(conn, uid, apartment_id)
        item = row_to_dict(row)
        item["score"] = scoring.score_apartment(conn, uid, row, request.app.state.router)
        item["status_history"] = [dict(r) for r in conn.execute(
            "SELECT status, at FROM apartment_status WHERE apartment_id = ? ORDER BY rowid", (apartment_id,))]
        return item

    @router.patch("/apartments/{apartment_id}")
    def patch_apartment(apartment_id: int, body: dict, ctx=Depends(me)):
        conn, uid = ctx
        row = own(conn, uid, apartment_id)
        merged = {**row_to_dict(row), **body}
        for key in ("id", "owner_id", "created", "updated", "status_history", "score", "place_score", "minutes"):
            merged.pop(key, None)
        try:
            checked = ApartmentIn(**merged)
        except Exception as exc:  # pydantic's ValidationError: report which fields
            raise HTTPException(422, str(exc))
        values = location({**checked.model_dump(), "location_source": merged.get("location_source")})
        values["facing"] = ",".join(values["facing"])
        # only the fields the client sent change; the rest keep their stored value
        sent = {k: v for k, v in values.items() if k in body or k == "location_source"}
        moved = ("lat" in body or "lon" in body) and (values["lat"], values["lon"]) != (row["lat"], row["lon"])
        if moved and "location_source" not in body:
            sent["location_source"] = "manual"
        sets = ", ".join(f"{k} = ?" for k in sent)
        with conn:
            conn.execute(f"UPDATE apartment SET {sets}, updated = ? WHERE id = ?", (*sent.values(), now(), apartment_id))
            if moved:
                conn.execute("DELETE FROM apartment_distance WHERE apartment_id = ?", (apartment_id,))
            if "status" in body and values["status"] != row["status"]:
                conn.execute("INSERT INTO apartment_status (apartment_id, status, at) VALUES (?,?,?)",
                             (apartment_id, values["status"], now()))
        return {"id": apartment_id}

    @router.delete("/apartments/{apartment_id}", status_code=204)
    def delete_apartment(apartment_id: int, ctx=Depends(me)):
        conn, uid = ctx
        own(conn, uid, apartment_id)
        with conn:
            conn.execute("DELETE FROM apartment WHERE id = ?", (apartment_id,))

    @router.get("/geocode")
    def geocode_address(q: str = Query(min_length=3, max_length=200), ctx=Depends(me)):
        try:
            return geocode.search(q, config.load_city()["bbox"])
        except geocode.NotConfigured:
            raise HTTPException(503, "no geocoder is configured; place the pin on the map")
        except Exception:
            raise HTTPException(502, "the geocoder did not answer; place the pin on the map")

    return router
