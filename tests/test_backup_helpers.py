"""Smoke tests for database backup and undo helpers."""

import os
import sqlite3

from services import backups


def _write_sqlite_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS smoke_test (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO smoke_test (name) VALUES ('ok')")
    conn.commit()
    conn.close()


def test_human_file_size():
    assert backups.human_file_size(0) == "0 B"
    assert backups.human_file_size(1024) == "1.0 KB"
    assert backups.human_file_size(1024 * 1024) == "1.0 MB"


def test_validate_sqlite_database(tmp_path):
    db_path = tmp_path / "valid.db"
    _write_sqlite_db(db_path)

    ok, message = backups.validate_sqlite_database(str(db_path))
    assert ok is True
    assert message == "ok"


def test_create_backup_and_undo_point(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    backup_dir = data_dir / "backups"
    undo_dir = data_dir / "undo"
    db_path = data_dir / "finance.db"

    data_dir.mkdir()
    _write_sqlite_db(db_path)

    monkeypatch.setattr(backups, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(backups, "DB_BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(backups, "DB_UNDO_DIR", str(undo_dir))
    monkeypatch.setattr(backups, "DB_NAME", str(db_path))
    monkeypatch.setattr(backups, "LEGACY_DB_NAME", str(tmp_path / "finance.db"))

    backup_path = backups.create_database_backup(prefix="pytest")
    assert backup_path is not None
    assert os.path.exists(backup_path)
    assert backups.list_database_backups()

    assert backups.save_undo_point("pytest undo") is True
    status = backups.get_undo_status()
    assert status["available"] is True
    assert status["points"]


def test_prune_directory_by_extension_keeps_newest(tmp_path):
    for idx in range(7):
        path = tmp_path / f"backup_{idx}.db"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (idx + 1, idx + 1))

    backups.prune_directory_by_extension(str(tmp_path), (".db",), keep_count=3)

    remaining = sorted(path.name for path in tmp_path.glob("*.db"))
    assert remaining == ["backup_4.db", "backup_5.db", "backup_6.db"]
