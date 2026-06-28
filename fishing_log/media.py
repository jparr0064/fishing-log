"""Photo storage — stubbed out in the cloud version (no local filesystem)."""
from __future__ import annotations
from typing import List


def load_image_oriented(file_obj):
    return None


def get_photos(session_id: int) -> List[dict]:
    return []


def delete_photo(photo_id: int) -> None:
    pass


def save_pil_images(session_id: int, images: list) -> List[int]:
    return []
