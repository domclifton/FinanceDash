"""Database backup, restore, undo, and storage helpers for InvestHome.

This module was extracted during the v3.0.0 backend refactor. It intentionally
contains filesystem and sqlite3 database-copy helpers only; Flask routes stay in
app.py until the later blueprint refactor steps.
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime

from config import (
    DATA_DIR,
    DB_BACKUP_DIR,
    DB_NAME,
    DB_UNDO_DIR,
    LEGACY_DB_NAME,
    MAX_DATABASE_BACKUPS,
    MAX_DATABASE_UNDO_POINTS,
)


def ensure_database_storage():
    """Keep runtime data out of the project root and migrate old installs safely."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    os.makedirs(DB_UNDO_DIR, exist_ok=True)

    if os.path.exists(LEGACY_DB_NAME) and not os.path.exists(DB_NAME):
        os.replace(LEGACY_DB_NAME, DB_NAME)
        for suffix in ("-wal", "-shm"):
            legacy_sidecar = LEGACY_DB_NAME + suffix
            new_sidecar = DB_NAME + suffix
            if os.path.exists(legacy_sidecar):
                os.replace(legacy_sidecar, new_sidecar)


def timestamp_for_filename():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def human_file_size(size_bytes):
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        size = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024


def validate_sqlite_database(path):
    try:
        conn = sqlite3.connect(path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        return result == "ok", result
    except Exception as exc:
        return False, str(exc)


def _timestamp_from_filename(filename):
    """Return best-effort sort key for backup/undo filenames."""
    try:
        return os.path.getmtime(filename)
    except OSError:
        return 0


def prune_directory_by_extension(directory, extensions, keep_count):
    """Keep the newest N files and remove older files plus matching metadata sidecars."""
    if keep_count <= 0 or not os.path.isdir(directory):
        return

    files = []
    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        if not filename.lower().endswith(tuple(extensions)):
            continue
        files.append(path)

    files.sort(key=_timestamp_from_filename, reverse=True)
    for old_path in files[keep_count:]:
        try:
            os.remove(old_path)
        except FileNotFoundError:
            pass

        stem, _ = os.path.splitext(old_path)
        for meta_ext in (".txt", ".json"):
            meta_path = stem + meta_ext
            if os.path.exists(meta_path):
                try:
                    os.remove(meta_path)
                except FileNotFoundError:
                    pass


def prune_database_backups():
    prune_directory_by_extension(DB_BACKUP_DIR, (".db", ".sqlite", ".sqlite3"), MAX_DATABASE_BACKUPS)


def prune_database_undo_points():
    prune_directory_by_extension(DB_UNDO_DIR, (".db", ".sqlite", ".sqlite3"), MAX_DATABASE_UNDO_POINTS)


def create_database_backup(prefix="manual"):
    """Create a consistent SQLite backup with a date-stamped filename."""
    ensure_database_storage()
    if not os.path.exists(DB_NAME):
        return None

    filename = f"finance_{timestamp_for_filename()}_{prefix}.db"
    destination = os.path.join(DB_BACKUP_DIR, filename)
    source_conn = sqlite3.connect(DB_NAME)
    backup_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()

    prune_database_backups()
    return destination


def list_database_backups():
    ensure_database_storage()
    backups = []
    for filename in os.listdir(DB_BACKUP_DIR):
        if not filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
            continue
        path = os.path.join(DB_BACKUP_DIR, filename)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        backups.append({
            "filename": filename,
            "size": human_file_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    backups.sort(key=lambda item: item["modified"], reverse=True)
    return backups


def _safe_undo_label(description):
    label = "".join(ch if ch.isalnum() else "_" for ch in str(description or "action"))
    label = "_".join(part for part in label.split("_") if part)
    return (label or "action")[:60]


def save_undo_point(description="Database action"):
    """Store a timestamped pre-action DB copy in a small undo ring buffer."""
    ensure_database_storage()
    if not os.path.exists(DB_NAME):
        return False

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    label = _safe_undo_label(description)
    undo_filename = f"undo_{stamp}_{label}.db"
    undo_path = os.path.join(DB_UNDO_DIR, undo_filename)

    source_conn = sqlite3.connect(DB_NAME)
    undo_conn = sqlite3.connect(undo_path)
    try:
        source_conn.backup(undo_conn)
    finally:
        undo_conn.close()
        source_conn.close()

    meta = {
        "filename": undo_filename,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": str(description or "Database action"),
    }
    meta_path = os.path.splitext(undo_path)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)

    prune_database_undo_points()
    return True


def list_database_undo_points():
    ensure_database_storage()
    points = []
    for filename in os.listdir(DB_UNDO_DIR):
        if not filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
            continue
        path = os.path.join(DB_UNDO_DIR, filename)
        if not os.path.isfile(path):
            continue

        stat = os.stat(path)
        item = {
            "filename": filename,
            "size": human_file_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "description": "Database action",
        }
        meta_path = os.path.splitext(path)[0] + ".json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as handle:
                    meta = json.load(handle)
                item["description"] = meta.get("description") or item["description"]
                item["modified"] = meta.get("created") or item["modified"]
            except (OSError, json.JSONDecodeError):
                pass
        points.append(item)

    points.sort(key=lambda item: item["modified"], reverse=True)
    return points


def get_undo_status():
    points = list_database_undo_points()
    latest = points[0] if points else None
    return {
        "available": bool(points),
        "description": latest["description"] if latest else None,
        "latest_filename": latest["filename"] if latest else None,
        "points": points,
        "limit": MAX_DATABASE_UNDO_POINTS,
    }


def replace_current_database(source_path):
    """Replace the active SQLite DB and clear stale WAL sidecar files."""
    ensure_database_storage()
    ok, message = validate_sqlite_database(source_path)
    if not ok:
        raise ValueError(f"Selected database failed integrity check: {message}")

    os.makedirs(DATA_DIR, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = DB_NAME + suffix
        if os.path.exists(target):
            os.remove(target)
    shutil.copy2(source_path, DB_NAME)
