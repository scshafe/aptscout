"""Apartment photos (design sections 7, 8.2, 10).

The browser resizes and re-encodes each photo to JPEG (which also drops the
camera's location tags) and sends the raw bytes. Files are stored under
`<data dir>/photos/<apartment id>/`, the owner's data: backed up with the
database, never in the repository.
"""

import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config
from .apartments_api import now
from .places_api import make_deps

MAX_BYTES = 4 * 1024 * 1024
JPEG_MAGIC = b"\xff\xd8\xff"


def photo_dir(apartment_id: int):
    return config.data_dir() / "photos" / str(apartment_id)


class CaptionIn(BaseModel):
    caption: str = Field(max_length=200)


def build_router(current_user) -> APIRouter:
    router = APIRouter(prefix="/api")
    me = make_deps(current_user)

    def own_apartment(conn, uid, apartment_id):
        if conn.execute("SELECT 1 FROM apartment WHERE id=? AND owner_id=?", (apartment_id, uid)).fetchone() is None:
            raise HTTPException(404)

    def own_photo(conn, uid, photo_id):
        row = conn.execute(
            "SELECT p.* FROM apartment_photo p JOIN apartment a ON a.id = p.apartment_id"
            " WHERE p.id = ? AND a.owner_id = ?", (photo_id, uid)).fetchone()
        if row is None:
            raise HTTPException(404)
        return row

    @router.get("/apartments/{apartment_id}/photos")
    def list_photos(apartment_id: int, ctx=Depends(me)):
        conn, uid = ctx
        own_apartment(conn, uid, apartment_id)
        return [{"id": r["id"], "caption": r["caption"], "created": r["created"]} for r in conn.execute(
            "SELECT * FROM apartment_photo WHERE apartment_id = ? ORDER BY id", (apartment_id,))]

    @router.post("/apartments/{apartment_id}/photos", status_code=201)
    async def add_photo(apartment_id: int, request: Request, ctx=Depends(me)):
        conn, uid = ctx
        own_apartment(conn, uid, apartment_id)
        if int(request.headers.get("content-length") or 0) > MAX_BYTES:
            raise HTTPException(413, "photo too large")
        data = await request.body()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "photo too large")
        if not data.startswith(JPEG_MAGIC):
            raise HTTPException(415, "send a JPEG")
        folder = photo_dir(apartment_id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.jpg"
        (folder / name).write_bytes(data)
        with conn:
            cur = conn.execute("INSERT INTO apartment_photo (apartment_id, file, created) VALUES (?,?,?)",
                               (apartment_id, name, now()))
        return {"id": cur.lastrowid}

    @router.get("/photos/{photo_id}")
    def get_photo(photo_id: int, ctx=Depends(me)):
        conn, uid = ctx
        row = own_photo(conn, uid, photo_id)
        path = photo_dir(row["apartment_id"]) / row["file"]
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @router.patch("/photos/{photo_id}")
    def caption_photo(photo_id: int, body: CaptionIn, ctx=Depends(me)):
        conn, uid = ctx
        own_photo(conn, uid, photo_id)
        with conn:
            conn.execute("UPDATE apartment_photo SET caption = ? WHERE id = ?", (body.caption, photo_id))
        return {"id": photo_id}

    @router.delete("/photos/{photo_id}", status_code=204)
    def delete_photo(photo_id: int, ctx=Depends(me)):
        conn, uid = ctx
        row = own_photo(conn, uid, photo_id)
        with conn:
            conn.execute("DELETE FROM apartment_photo WHERE id = ?", (photo_id,))
        (photo_dir(row["apartment_id"]) / row["file"]).unlink(missing_ok=True)

    return router


def remove_apartment_files(apartment_id: int) -> None:
    shutil.rmtree(photo_dir(apartment_id), ignore_errors=True)
