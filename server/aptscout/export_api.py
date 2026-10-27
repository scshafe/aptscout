"""Export and import of the owner's data (design section 10).

JSON holds everything that is the owner's and cannot be rebuilt from public data:
apartments (with status history), destinations, categories and weights, the
owner's own places, marks on imported places and settings. Photos are files; they
are covered by the backup, not by this export. CSV is the comparison table.
"""

import csv
import io
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from . import categories, scoring
from .apartments_api import ApartmentIn, now
from .destinations_api import DestinationIn
from .places_api import make_deps

VERSION = 1
CATEGORY_COLUMNS = ("key", "name", "colour", "icon", "builtin", "visible", "weight", "measure", "d_good", "d_max", "aggregation")
PLACE_COLUMNS = ("category_key", "name", "lat", "lon", "address", "notes")


def export_data(conn: sqlite3.Connection, uid: int) -> dict:
    cats = [dict(r) for r in conn.execute(
        f"SELECT {', '.join(CATEGORY_COLUMNS)} FROM category WHERE owner_id = ? ORDER BY id", (uid,))]
    own = []
    for r in conn.execute("SELECT p.*, COALESCE(m.state,'unreviewed') AS state, COALESCE(m.favourite,0) AS favourite,"
                          " COALESCE(m.hidden,0) AS hidden FROM place p LEFT JOIN place_mark m ON m.place_id = p.id AND m.owner_id = ?"
                          " WHERE p.owner_id = ? ORDER BY p.id", (uid, uid)):
        own.append({**{k: r[k] for k in PLACE_COLUMNS}, "state": r["state"], "favourite": bool(r["favourite"]), "hidden": bool(r["hidden"])})
    marks = [{"ext_id": r["ext_id"], "state": r["state"], "favourite": bool(r["favourite"]), "hidden": bool(r["hidden"]), "notes": r["notes"]}
             for r in conn.execute(
                 "SELECT p.ext_id, m.* FROM place_mark m JOIN place p ON p.id = m.place_id"
                 " WHERE m.owner_id = ? AND p.owner_id IS NULL AND p.ext_id IS NOT NULL ORDER BY p.id", (uid,))]
    apartments = []
    for r in conn.execute("SELECT * FROM apartment WHERE owner_id = ? ORDER BY id", (uid,)):
        item = {k: r[k] for k in r.keys() if k not in ("id", "owner_id")}
        item["facing"] = [f for f in r["facing"].split(",") if f]
        item["status_history"] = [dict(h) for h in conn.execute(
            "SELECT status, at FROM apartment_status WHERE apartment_id = ? ORDER BY rowid", (r["id"],))]
        apartments.append(item)
    dests = [{k: r[k] for k in r.keys() if k not in ("id", "owner_id")} for r in conn.execute(
        "SELECT * FROM destination WHERE owner_id = ? ORDER BY id", (uid,))]
    settings = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM setting WHERE owner_id = ?", (uid,))}
    return {"aptscout_export": VERSION, "exported": now(), "categories": cats, "places": own, "marks": marks,
            "apartments": apartments, "destinations": dests, "settings": settings}


def import_data(conn: sqlite3.Connection, uid: int, data: dict) -> dict:
    """Replace the owner's data with an export. Validates everything first; all or nothing."""
    if data.get("aptscout_export") != VERSION:
        raise ValueError("not an aptscout export (or a newer version)")
    apartments = [(ApartmentIn(**{k: v for k, v in a.items() if k != "status_history"}), a) for a in data.get("apartments", [])]
    dests = [DestinationIn(**d) for d in data.get("destinations", [])]
    known_cats = {c["key"] for c in data.get("categories", [])} | {key for key, *_ in categories.BUILTIN}
    for p in data.get("places", []):
        if p["category_key"] not in known_cats:
            raise ValueError(f"place {p['name']!r} has an unknown category")
    stats = {"apartments": len(apartments), "destinations": len(dests), "places": len(data.get("places", [])), "marks_skipped": 0}
    with conn:
        conn.execute("DELETE FROM apartment WHERE owner_id = ?", (uid,))
        conn.execute("DELETE FROM destination WHERE owner_id = ?", (uid,))
        conn.execute("DELETE FROM place WHERE owner_id = ?", (uid,))
        conn.execute("DELETE FROM place_mark WHERE owner_id = ?", (uid,))
        conn.execute("DELETE FROM category WHERE owner_id = ? AND builtin = 0", (uid,))
        conn.execute("DELETE FROM setting WHERE owner_id = ?", (uid,))
        for c in data.get("categories", []):
            row = {k: c[k] for k in CATEGORY_COLUMNS if k in c}
            if row.get("builtin"):
                sets = ", ".join(f"{k} = ?" for k in row if k not in ("key", "builtin"))
                conn.execute(f"UPDATE category SET {sets} WHERE owner_id = ? AND key = ?",
                             (*[v for k, v in row.items() if k not in ("key", "builtin")], uid, row["key"]))
            else:
                conn.execute(f"INSERT INTO category (owner_id, {', '.join(row)}) VALUES (?, {', '.join('?' * len(row))})", (uid, *row.values()))
        for p in data.get("places", []):
            cur = conn.execute(
                "INSERT INTO place (category_key, owner_id, source, name, lat, lon, address, notes, edited) VALUES (?,?,?,?,?,?,?,?,1)",
                (p["category_key"], uid, "manual", p["name"], p["lat"], p["lon"], p.get("address", ""), p.get("notes", "")))
            conn.execute("INSERT INTO place_mark (owner_id, place_id, state, favourite, hidden) VALUES (?,?,?,?,?)",
                         (uid, cur.lastrowid, p.get("state", "unreviewed"), int(p.get("favourite", False)), int(p.get("hidden", False))))
        for m in data.get("marks", []):
            place = conn.execute("SELECT id FROM place WHERE ext_id = ?", (m["ext_id"],)).fetchone()
            if place is None:
                stats["marks_skipped"] += 1
                continue
            conn.execute("INSERT OR REPLACE INTO place_mark (owner_id, place_id, state, favourite, hidden, notes) VALUES (?,?,?,?,?,?)",
                         (uid, place["id"], m.get("state", "unreviewed"), int(m.get("favourite", False)), int(m.get("hidden", False)), m.get("notes", "")))
        for checked, raw in apartments:
            values = checked.model_dump()
            values["facing"] = ",".join(values["facing"])
            values["location_source"] = values["location_source"] or ("manual" if values["lat"] is not None else "none")
            created = raw.get("created") or now()
            cur = conn.execute(
                f"INSERT INTO apartment (owner_id, created, updated, {', '.join(values)}) VALUES (?,?,?,{', '.join('?' * len(values))})",
                (uid, created, raw.get("updated") or created, *values.values()))
            history = raw.get("status_history") or [{"status": values["status"], "at": created}]
            for h in history:
                conn.execute("INSERT INTO apartment_status (apartment_id, status, at) VALUES (?,?,?)", (cur.lastrowid, h["status"], h["at"]))
        for d in dests:
            values = d.model_dump()
            conn.execute(f"INSERT INTO destination (owner_id, {', '.join(values)}) VALUES (?, {', '.join('?' * len(values))})", (uid, *values.values()))
        for key, value in (data.get("settings") or {}).items():
            conn.execute("INSERT INTO setting (owner_id, key, value) VALUES (?,?,?)", (uid, key, json.dumps(value)))
    return stats


def csv_safe(value) -> str:
    """Spreadsheets run cells that start with = + - @ as formulas; defuse them."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def comparison_csv(conn: sqlite3.Connection, uid: int, router, otp=None) -> str:
    from . import weekly

    cats = conn.execute("SELECT * FROM category WHERE owner_id = ? AND weight > 0 ORDER BY weight DESC, id", (uid,)).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["label", "address", "unit", "status", "rent", "fees", "beds", "baths", "sqft", "floor", "floors_in_building",
                     "facing", "listing_url", "notes", "place_score", "weekly_minutes", *[f"walk_min_{c['key']}" for c in cats]])
    for a in conn.execute("SELECT * FROM apartment WHERE owner_id = ? ORDER BY id", (uid,)):
        result = scoring.score_apartment(conn, uid, a, router)
        trips = weekly.weekly_for_apartment(conn, uid, a, router, otp)
        per = {c["key"]: c["minutes"] for c in result["categories"]}
        writer.writerow([csv_safe(v) for v in [
            a["label"], a["address"], a["unit"], a["status"], a["rent"], a["fees"], a["beds"], a["baths"], a["sqft"], a["floor"],
            a["floors_in_building"], " ".join(f for f in a["facing"].split(",") if f), a["listing_url"], a["notes"],
            result["place_score"], trips["total"], *[per.get(c["key"]) for c in cats]]])
    return out.getvalue()


def build_router(current_user) -> APIRouter:
    router = APIRouter(prefix="/api")
    me = make_deps(current_user)

    @router.get("/export")
    def export(ctx=Depends(me)):
        conn, uid = ctx
        body = json.dumps(export_data(conn, uid), indent=2)
        return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="aptscout-export.json"'})

    @router.get("/export.csv")
    def export_csv(request: Request, ctx=Depends(me)):
        conn, uid = ctx
        body = comparison_csv(conn, uid, request.app.state.router, request.app.state.otp)
        return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="aptscout-compare.csv"'})

    @router.post("/import")
    async def import_(request: Request, replace: bool = False, ctx=Depends(me)):
        if not replace:
            raise HTTPException(409, "importing replaces all of your apartments, destinations and categories; send ?replace=true")
        conn, uid = ctx
        try:
            return import_data(conn, uid, await request.json())
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, f"could not import: {exc}"[:300])

    return router
