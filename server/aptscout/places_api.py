"""Categories and places (design sections 3.2, 3.3, 7). Private rows are per owner."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import categories, db

CATEGORY_FIELDS = ("name", "colour", "icon", "visible", "weight", "measure", "d_good", "d_max", "aggregation")
MEASURES = ("straight", "walk_distance", "walk_time")
AGGREGATIONS = ("nearest", "mean_n", "favourite")


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def owner_id(conn: sqlite3.Connection, subject: str) -> int:
    conn.execute("INSERT OR IGNORE INTO app_user (subject, name) VALUES (?, ?)", (subject, subject))
    conn.commit()
    uid = conn.execute("SELECT id FROM app_user WHERE subject = ?", (subject,)).fetchone()["id"]
    categories.seed_user_categories(conn, uid)
    return uid


def make_deps(current_user):
    def me(conn: sqlite3.Connection = Depends(get_conn), subject: str = Depends(current_user)):
        return conn, owner_id(conn, subject)
    return me


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str = Field(default="", max_length=8)


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    colour: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=8)
    visible: bool | None = None
    weight: float | None = Field(default=None, ge=0, le=10)
    measure: str | None = None
    d_good: float | None = Field(default=None, ge=0)
    d_max: float | None = Field(default=None, ge=0)
    aggregation: str | None = None


class PlaceIn(BaseModel):
    category: str
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)


class PlacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    state: str | None = None
    favourite: bool | None = None
    hidden: bool | None = None


def category_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["visible"] = bool(out["visible"])
    out["builtin"] = bool(out["builtin"])
    out["transit"] = out["key"] in categories.TRANSIT
    return out


def build_router(current_user) -> APIRouter:
    router = APIRouter(prefix="/api")
    me = make_deps(current_user)

    @router.get("/categories")
    def list_categories(ctx=Depends(me)):
        conn, uid = ctx
        rows = conn.execute("SELECT * FROM category WHERE owner_id = ? ORDER BY builtin DESC, id", (uid,)).fetchall()
        return [category_row(r) for r in rows]

    @router.post("/categories", status_code=201)
    def add_category(body: CategoryIn, ctx=Depends(me)):
        conn, uid = ctx
        key = "u-" + db.slug(body.name)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO category (owner_id, key, name, colour, icon) VALUES (?,?,?,?,?)",
                    (uid, key, body.name, body.colour, body.icon),
                )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "a category with that name exists")
        return category_row(conn.execute("SELECT * FROM category WHERE owner_id=? AND key=?", (uid, key)).fetchone())

    @router.patch("/categories/{key}")
    def patch_category(key: str, body: CategoryPatch, ctx=Depends(me)):
        conn, uid = ctx
        changes = body.model_dump(exclude_none=True)
        if "measure" in changes and changes["measure"] not in MEASURES:
            raise HTTPException(422, f"measure must be one of {MEASURES}")
        if "aggregation" in changes and changes["aggregation"] not in AGGREGATIONS:
            raise HTTPException(422, f"aggregation must be one of {AGGREGATIONS}")
        if "visible" in changes:
            changes["visible"] = int(changes["visible"])
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)  # keys come from the model, not the client
            with conn:
                cur = conn.execute(f"UPDATE category SET {sets} WHERE owner_id = ? AND key = ?", (*changes.values(), uid, key))
            if cur.rowcount == 0:
                raise HTTPException(404)
        row = conn.execute("SELECT * FROM category WHERE owner_id = ? AND key = ?", (uid, key)).fetchone()
        if row is None:
            raise HTTPException(404)
        return category_row(row)

    @router.delete("/categories/{key}", status_code=204)
    def delete_category(key: str, ctx=Depends(me)):
        conn, uid = ctx
        row = conn.execute("SELECT builtin FROM category WHERE owner_id=? AND key=?", (uid, key)).fetchone()
        if row is None:
            raise HTTPException(404)
        if row["builtin"]:
            raise HTTPException(409, "a shipped category can be hidden but not deleted")
        with conn:
            conn.execute("DELETE FROM place WHERE owner_id = ? AND category_key = ?", (uid, key))
            conn.execute("DELETE FROM category WHERE owner_id = ? AND key = ?", (uid, key))

    @router.get("/places")
    def list_places(
        ctx=Depends(me),
        category: Annotated[list[str] | None, Query()] = None,
        include_hidden: bool = False,
        include_transit: bool = False,
    ):
        """GeoJSON of the places the owner can see, with the owner's marks."""
        conn, uid = ctx
        sql = (
            "SELECT p.*, COALESCE(m.state,'unreviewed') AS state, COALESCE(m.favourite,0) AS favourite,"
            " COALESCE(m.hidden,0) AS hidden, COALESCE(m.notes,'') AS mark_notes, c.colour AS colour,"
            " c.name AS category_name"
            " FROM place p JOIN category c ON c.owner_id = ? AND c.key = p.category_key"
            " LEFT JOIN place_mark m ON m.owner_id = ? AND m.place_id = p.id"
            " WHERE p.gone = 0 AND (p.owner_id IS NULL OR p.owner_id = ?)"
        )
        args: list = [uid, uid, uid]
        if category:
            sql += " AND p.category_key IN (%s)" % ",".join("?" * len(category))
            args += category
        elif not include_transit:
            sql += " AND p.category_key NOT IN (%s)" % ",".join("?" * len(categories.TRANSIT))
            args += sorted(categories.TRANSIT)
        if not include_hidden:
            sql += " AND COALESCE(m.hidden,0) = 0"
        features = []
        for r in conn.execute(sql, args):
            notes = "\n".join(n for n in (r["notes"], r["mark_notes"]) if n)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {
                    "id": r["id"], "name": r["name"], "category": r["category_key"],
                    "category_name": r["category_name"], "colour": r["colour"], "source": r["source"],
                    "address": r["address"], "lap_score": r["lap_score"], "also": r["also"],
                    "state": r["state"], "favourite": bool(r["favourite"]), "hidden": bool(r["hidden"]),
                    "notes": notes, "own": r["owner_id"] is not None,
                },
            })
        return {"type": "FeatureCollection", "features": features}

    @router.post("/places", status_code=201)
    def add_place(body: PlaceIn, ctx=Depends(me)):
        conn, uid = ctx
        if conn.execute("SELECT 1 FROM category WHERE owner_id=? AND key=?", (uid, body.category)).fetchone() is None:
            raise HTTPException(422, "unknown category")
        with conn:
            cur = conn.execute(
                "INSERT INTO place (category_key, owner_id, source, name, lat, lon, address, notes, edited)"
                " VALUES (?,?,?,?,?,?,?,?,1)",
                (body.category, uid, "manual", body.name, body.lat, body.lon, body.address, body.notes),
            )
        return {"id": cur.lastrowid}

    @router.patch("/places/{place_id}")
    def patch_place(place_id: int, body: PlacePatch, ctx=Depends(me)):
        conn, uid = ctx
        place = conn.execute("SELECT * FROM place WHERE id = ?", (place_id,)).fetchone()
        if place is None or place["owner_id"] not in (None, uid):
            raise HTTPException(404)
        changes = body.model_dump(exclude_none=True)
        if "state" in changes and changes["state"] not in categories.LAP_POOL_STATES:
            raise HTTPException(422, f"state must be one of {categories.LAP_POOL_STATES}")
        row_fields = {k: changes[k] for k in ("name", "lat", "lon", "address") if k in changes}
        with conn:
            if row_fields:
                sets = ", ".join(f"{k} = ?" for k in row_fields)
                conn.execute(f"UPDATE place SET {sets}, edited = 1 WHERE id = ?", (*row_fields.values(), place_id))
                if "lat" in row_fields or "lon" in row_fields:
                    conn.execute("DELETE FROM apartment_distance WHERE place_id = ?", (place_id,))
            if place["owner_id"] is not None and "notes" in changes:
                conn.execute("UPDATE place SET notes = ? WHERE id = ?", (changes["notes"], place_id))
            marks = {k: changes[k] for k in ("state", "favourite", "hidden") if k in changes}
            if place["owner_id"] is None and "notes" in changes:
                marks["notes"] = changes["notes"]
            if marks:
                marks = {k: int(v) if isinstance(v, bool) else v for k, v in marks.items()}
                conn.execute("INSERT OR IGNORE INTO place_mark (owner_id, place_id) VALUES (?, ?)", (uid, place_id))
                sets = ", ".join(f"{k} = ?" for k in marks)
                conn.execute(f"UPDATE place_mark SET {sets} WHERE owner_id = ? AND place_id = ?", (*marks.values(), uid, place_id))
        return {"id": place_id}

    @router.delete("/places/{place_id}", status_code=204)
    def delete_place(place_id: int, ctx=Depends(me)):
        """Delete an owner's own place; an imported place is hidden instead."""
        conn, uid = ctx
        place = conn.execute("SELECT owner_id FROM place WHERE id = ?", (place_id,)).fetchone()
        if place is None or place["owner_id"] not in (None, uid):
            raise HTTPException(404)
        with conn:
            if place["owner_id"] is None:
                conn.execute("INSERT OR IGNORE INTO place_mark (owner_id, place_id) VALUES (?, ?)", (uid, place_id))
                conn.execute("UPDATE place_mark SET hidden = 1 WHERE owner_id = ? AND place_id = ?", (uid, place_id))
            else:
                conn.execute("DELETE FROM place WHERE id = ?", (place_id,))

    return router
