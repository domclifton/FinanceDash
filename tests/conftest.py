"""Shared pytest fixtures for InvestHome smoke tests.

The app currently runs startup database initialisation during import, so these
fixtures redirect runtime database paths to a temporary directory before the app
module is imported. This keeps smoke tests away from a real self-hosted
finance.db file.
"""

import importlib
import sys

import pytest


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    """Import app.py with runtime data paths redirected to a temp folder."""
    pytest.importorskip("flask")

    temp_root = tmp_path_factory.mktemp("investhome-runtime")
    data_dir = temp_root / "data"
    backup_dir = data_dir / "backups"
    undo_dir = data_dir / "undo"

    import config

    config.DATA_DIR = str(data_dir)
    config.DB_BACKUP_DIR = str(backup_dir)
    config.DB_UNDO_DIR = str(undo_dir)
    config.DB_NAME = str(data_dir / "finance.db")
    config.LEGACY_DB_NAME = str(temp_root / "finance.db")

    # services.backups may already have been imported during test collection,
    # so keep its copied config globals aligned with the temporary DB paths.
    import services.backups as backup_service

    backup_service.DATA_DIR = config.DATA_DIR
    backup_service.DB_BACKUP_DIR = config.DB_BACKUP_DIR
    backup_service.DB_UNDO_DIR = config.DB_UNDO_DIR
    backup_service.DB_NAME = config.DB_NAME
    backup_service.LEGACY_DB_NAME = config.LEGACY_DB_NAME

    sys.modules.pop("app", None)
    return importlib.import_module("app")
