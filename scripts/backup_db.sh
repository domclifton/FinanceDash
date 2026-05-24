#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

mkdir -p data/backups

DB_PATH="data/finance.db"
LEGACY_DB_PATH="finance.db"

if [ ! -f "$DB_PATH" ] && [ -f "$LEGACY_DB_PATH" ]; then
    echo "Moving legacy finance.db into data/"
    mv "$LEGACY_DB_PATH" "$DB_PATH"
    [ -f "${LEGACY_DB_PATH}-wal" ] && mv "${LEGACY_DB_PATH}-wal" "${DB_PATH}-wal"
    [ -f "${LEGACY_DB_PATH}-shm" ] && mv "${LEGACY_DB_PATH}-shm" "${DB_PATH}-shm"
fi

if [ ! -f "$DB_PATH" ]; then
    echo "No data/finance.db found. Nothing to back up."
    exit 0
fi

BACKUP="data/backups/finance_$(date +%F_%H-%M-%S)_script.db"
python3 - <<PYSQL
import sqlite3
source = sqlite3.connect("$DB_PATH")
destination = sqlite3.connect("$BACKUP")
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PYSQL

echo "Backup created: $BACKUP"
