"""Destinations, the owner's settings and the weekly travel time (design section 5)."""

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import weekly
from .places_api import make_deps

SETTINGS = {  # key -> (lowest, highest) for the combined score's sliders
    "w_place": (0, 10), "w_time": (0, 10), "w_rent": (0, 10),
}
BOOL_SETTINGS = ("combined_on",)


class DestinationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    address: str = Field(default="", max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    category_key: str | None = None
    selection_rule: str = "best"
    n: int = Field(default=3, ge=1, le=10)
    trips_per_week: float = Field(default=1, ge=0, le=200)
    mode: str = "walk"
    time_band: str = "weekday_midday"
    return_band: str | None = None
    max_minutes: int | None = Field(default=None, ge=1, le=600)

    @model_validator(mode="after")
    def _check(self):
        if self.kind not in ("place", "category"):
            raise ValueError("kind must be 'place' or 'category'")
        if self.mode not in weekly.MODES:
            raise ValueError(f"mode must be one of {weekly.MODES}")
        if self.selection_rule not in weekly.SELECTION_RULES:
            raise ValueError(f"selection_rule must be one of {weekly.SELECTION_RULES}")
        for band in (self.time_band, self.return_band):
            if band is not None and band not in weekly.BANDS:
                raise ValueError(f"time bands are {weekly.BANDS}")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon go together")
        if self.kind == "category" and not self.category_key:
            raise ValueError("a category destination needs category_key")
        return self


def build_router(current_user) -> APIRouter:
    router = APIRouter(prefix="/api")
    me = make_deps(current_user)

    def own(conn, uid, dest_id) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM destination WHERE id = ? AND owner_id = ?", (dest_id, uid)).fetchone()
        if row is None:
            raise HTTPException(404)
        return row

    def check_category(conn, uid, body: DestinationIn):
        if body.kind == "category" and conn.execute(
                "SELECT 1 FROM category WHERE owner_id=? AND key=?", (uid, body.category_key)).fetchone() is None:
            raise HTTPException(422, "unknown category")

    @router.get("/destinations")
    def list_destinations(ctx=Depends(me)):
        conn, uid = ctx
        return [{k: r[k] for k in r.keys() if k != "owner_id"} for r in conn.execute(
            "SELECT * FROM destination WHERE owner_id = ? ORDER BY id", (uid,))]

    @router.post("/destinations", status_code=201)
    def add_destination(body: DestinationIn, ctx=Depends(me)):
        conn, uid = ctx
        check_category(conn, uid, body)
        values = body.model_dump()
        with conn:
            cur = conn.execute(
                f"INSERT INTO destination (owner_id, {', '.join(values)}) VALUES (?, {', '.join('?' * len(values))})",
                (uid, *values.values()))
        return {"id": cur.lastrowid}

    @router.patch("/destinations/{dest_id}")
    def patch_destination(dest_id: int, body: dict, ctx=Depends(me)):
        conn, uid = ctx
        row = own(conn, uid, dest_id)
        merged = {k: v for k, v in dict(row).items() if k not in ("id", "owner_id")} | body
        try:
            checked = DestinationIn(**merged)
        except Exception as exc:
            raise HTTPException(422, str(exc))
        check_category(conn, uid, checked)
        values = checked.model_dump()
        # trips per week only multiplies cached one-way times; anything else changes what is travelled
        changed_route = any(values[k] != row[k] for k in ("kind", "lat", "lon", "category_key", "selection_rule",
                                                           "n", "mode", "time_band", "return_band"))
        with conn:
            sets = ", ".join(f"{k} = ?" for k in values)
            conn.execute(f"UPDATE destination SET {sets} WHERE id = ?", (*values.values(), dest_id))
            if changed_route:
                conn.execute("DELETE FROM travel_time WHERE destination_id = ?", (dest_id,))
        return {"id": dest_id}

    @router.delete("/destinations/{dest_id}", status_code=204)
    def delete_destination(dest_id: int, ctx=Depends(me)):
        conn, uid = ctx
        own(conn, uid, dest_id)
        with conn:
            conn.execute("DELETE FROM destination WHERE id = ?", (dest_id,))

    @router.get("/settings")
    def get_settings(ctx=Depends(me)):
        conn, uid = ctx
        stored = {r["key"]: json.loads(r["value"]) for r in conn.execute(
            "SELECT key, value FROM setting WHERE owner_id = ?", (uid,))}
        return {"combined_on": False, "w_place": 5, "w_time": 8, "w_rent": 3} | stored

    @router.put("/settings")
    def put_settings(body: dict, ctx=Depends(me)):
        conn, uid = ctx
        for key, value in body.items():
            if key in BOOL_SETTINGS and isinstance(value, bool):
                continue
            low_high = SETTINGS.get(key)
            if low_high is None or isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not low_high[0] <= value <= low_high[1]:
                raise HTTPException(422, f"bad setting {key!r}")
        with conn:
            for key, value in body.items():
                conn.execute("INSERT OR REPLACE INTO setting (owner_id, key, value) VALUES (?,?,?)",
                             (uid, key, json.dumps(value)))
        return get_settings(ctx)

    return router
