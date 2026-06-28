"""Photo storage for fishing sessions.

Image files are written to ``data/photos/<session_id>/`` and their paths
(relative to the project root) are recorded in the ``photos`` table. Keeping
the bytes on disk rather than in SQLite keeps the database small and the
images easy to browse.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import List

from PIL import Image, ImageOps

from . import database as db

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def load_image_oriented(file_or_path) -> "Image.Image":
    """Open an image and bake in its EXIF orientation.

    Phone/camera photos are often stored rotated with an EXIF orientation flag;
    without applying it the image appears sideways in the app even though it
    looks upright in a desktop viewer. exif_transpose rotates the pixels and
    clears the flag so what you see is what gets saved.
    """
    return ImageOps.exif_transpose(Image.open(file_or_path))


def save_uploaded_photos(session_id: int, files: List) -> List[str]:
    """Persist Streamlit UploadedFile objects for a session.

    Returns the list of stored relative paths. Unsupported extensions skipped.
    """
    if not files:
        return []
    dest = db.PHOTOS_DIR / str(session_id)
    dest.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    conn = db.get_connection()
    try:
        for f in files:
            ext = Path(getattr(f, "name", "photo")).suffix.lower()
            if ext not in ALLOWED_EXTS:
                continue
            fname = f"{uuid.uuid4().hex}{ext}"
            fpath = dest / fname
            with open(fpath, "wb") as out:
                out.write(f.getbuffer())
            rel = str(fpath.relative_to(db.PROJECT_ROOT))
            db.insert_photo(conn, session_id, rel)
            saved.append(rel)
        conn.commit()
    finally:
        conn.close()
    return saved


def save_pil_images(session_id: int, images: List, captions: List = None) -> List[str]:
    """Persist already-edited PIL images (rotated/cropped) as JPEGs.

    Returns the list of stored relative paths.
    """
    if not images:
        return []
    dest = db.PHOTOS_DIR / str(session_id)
    dest.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    conn = db.get_connection()
    try:
        for i, img in enumerate(images):
            fname = f"{uuid.uuid4().hex}.jpg"
            fpath = dest / fname
            img.convert("RGB").save(fpath, format="JPEG", quality=90)
            rel = str(fpath.relative_to(db.PROJECT_ROOT))
            caption = captions[i] if captions and i < len(captions) else None
            db.insert_photo(conn, session_id, rel, caption)
            saved.append(rel)
        conn.commit()
    finally:
        conn.close()
    return saved


def get_photos(session_id: int) -> List[dict]:
    """Return [{id, path, caption, abs_path}] for a session's photos."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, path, caption FROM photos WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["abs_path"] = str(db.PROJECT_ROOT / d["path"])
        result.append(d)
    return result


def delete_photo(photo_id: int) -> None:
    """Delete a single photo (DB row + file on disk)."""
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT path FROM photos WHERE id = ?", (photo_id,)).fetchone()
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        conn.commit()
    finally:
        conn.close()
    if row:
        fpath = db.PROJECT_ROOT / row["path"]
        if fpath.exists():
            fpath.unlink()


def delete_session_photos(session_id: int) -> None:
    """Remove a single session's photo folder from disk."""
    folder = db.PHOTOS_DIR / str(session_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def delete_all_photos() -> None:
    """Remove every stored photo folder from disk."""
    if db.PHOTOS_DIR.exists():
        shutil.rmtree(db.PHOTOS_DIR, ignore_errors=True)
