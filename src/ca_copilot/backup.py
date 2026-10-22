"""Backup and restore for the local data directory.

- Backup = one timestamped ZIP containing app.db, config.json, documents/,
  and reports/. Nothing is uploaded anywhere; the ZIP stays in backups/.
- Restore = extract a backup ZIP into a chosen (empty or new) data directory,
  or overwrite the current one after an explicit confirmation in the UI.
- Backups never delete user data on their own.
"""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from . import paths

_BACKUP_ITEMS = ("app.db", "config.json", "config.yaml", "documents", "reports")


def create_backup(dest_dir: Path | None = None) -> Path:
    """Create a timestamped ZIP backup of user data. Returns the ZIP path."""
    data = paths.data_dir()
    dest_dir = dest_dir or paths.backups_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    zip_path = dest_dir / f"ca-copilot-backup-{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in _BACKUP_ITEMS:
            src = data / item
            if not src.exists():
                continue
            if src.is_dir():
                for f in sorted(src.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(data))
            else:
                zf.write(src, src.relative_to(data))
    return zip_path


def list_backups(dest_dir: Path | None = None) -> list[Path]:
    dest_dir = dest_dir or paths.backups_dir()
    if not dest_dir.exists():
        return []
    return sorted(dest_dir.glob("ca-copilot-backup-*.zip"), reverse=True)


def inspect_backup(zip_path: Path) -> dict:
    """List what's inside a backup without restoring it."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    return {"path": str(zip_path),
            "files": len(names),
            "size_bytes": Path(zip_path).stat().st_size,
            "has_database": "app.db" in names,
            "has_config": "config.json" in names or "config.yaml" in names}


def restore_backup(zip_path: Path, target_dir: Path) -> Path:
    """Extract a backup into target_dir. target_dir must be empty or non-existent.

    Raises ValueError otherwise — restore never merges into a live data dir
    without the user explicitly choosing it in the UI.
    """
    zip_path = Path(zip_path)
    target_dir = Path(target_dir)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Not a valid backup ZIP file.")
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError(
            "Restore target must be empty. Pick an empty folder, or delete/rename "
            "the current data directory first (after taking a fresh backup).")
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # Zip-slip protection: refuse absolute paths or '..' entries.
        for name in zf.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Unsafe entry in backup: {name}")
        zf.extractall(target_dir)
    return target_dir
