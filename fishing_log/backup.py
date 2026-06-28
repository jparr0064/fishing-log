"""Database backup, restore, and CSV export helpers.

Backups are timestamped copies of the SQLite file in ``data/backups/``. The app
makes one automatically on startup and keeps the most recent ``MAX_KEEP``.
"""
from __future__ import annotations

import datetime
import shutil
from pathlib import Path
from typing import List, Optional

from . import database as db

BACKUP_DIR = db.DATA_DIR / "backups"
MAX_KEEP = 10
_PATTERN = "fishing_log-*.db"


def auto_backup(max_keep: int = MAX_KEEP) -> Optional[Path]:
    """Copy the live DB to a timestamped backup and prune old ones."""
    src = Path(db.get_db_path())
    if str(src) == ":memory:" or not src.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUP_DIR / f"fishing_log-{ts}.db"
    if not dst.exists():
        shutil.copy2(src, dst)
    _prune(max_keep)
    return dst


def _prune(max_keep: int) -> None:
    backups = sorted(BACKUP_DIR.glob(_PATTERN))
    for old in backups[: max(0, len(backups) - max_keep)]:
        old.unlink(missing_ok=True)


def list_backups() -> List[Path]:
    """Backups, newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob(_PATTERN), reverse=True)


def restore_backup(path: str | Path) -> None:
    """Replace the live DB with a backup (after safety-copying the current one)."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Backup not found: {src}")
    auto_backup()  # snapshot current state before overwriting
    shutil.copy2(src, Path(db.get_db_path()))
