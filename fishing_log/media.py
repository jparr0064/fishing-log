"""Photo storage — cloud version: JPEG bytes stored in the photos table."""
from __future__ import annotations
import io
from typing import List

from . import database as db


def load_image_oriented(file_obj):
    """Load a PIL Image from an uploaded file, auto-rotating via EXIF."""
    from PIL import Image, ImageOps
    img = Image.open(file_obj)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img


def _to_jpeg_bytes(pil_image) -> bytes:
    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def save_pil_images(session_id: int, images: list) -> List[int]:
    """Compress and store PIL images in the photos table. Returns new photo IDs."""
    from sqlalchemy import text
    user_email = db.get_current_user()
    ids = []
    with db.get_engine().begin() as conn:
        for img in images:
            data = _to_jpeg_bytes(img)
            result = conn.execute(
                text(
                    "INSERT INTO photos (session_id, user_email, data) "
                    "VALUES (:sid, :email, :data) RETURNING id"
                ),
                {"sid": session_id, "email": user_email, "data": data},
            )
            ids.append(int(result.scalar()))
    return ids


def get_photos(session_id: int) -> List[dict]:
    """Return photos for a session as list of {id, data (bytes), caption}."""
    from sqlalchemy import text
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, data, caption FROM photos "
                "WHERE session_id = :sid AND data IS NOT NULL ORDER BY id"
            ),
            {"sid": session_id},
        ).mappings().all()
    return [{"id": r["id"], "data": bytes(r["data"]), "caption": r["caption"]} for r in rows]


def delete_photo(photo_id: int) -> None:
    from sqlalchemy import text
    with db.get_engine().begin() as conn:
        conn.execute(text("DELETE FROM photos WHERE id = :id"), {"id": photo_id})
