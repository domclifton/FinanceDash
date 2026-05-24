"""Settings routes for InvestHome.

This blueprint is intentionally thin: it keeps the same settings/database
behaviour as the original monolithic app while moving the route handlers out of
app.py as the first route extraction step in the v3 refactor.
"""

import os
import tempfile

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from config import (
    APP_DIR,
    DB_BACKUP_DIR,
    DB_NAME,
    DB_UNDO_DIR,
    GOLDAPI_KEY,
    TRADING212_AUTO_ACCOUNT_NAME,
    TRADING212_AUTO_ACCOUNT_TYPE,
)
from db import get_db, get_setting, set_setting
from services.backups import (
    create_database_backup,
    get_undo_status,
    list_database_backups,
    list_database_undo_points,
    replace_current_database,
    validate_sqlite_database,
)
from services.trading212 import (
    trading212_credentials_present,
    trading212_get_settings,
)


def create_settings_blueprint(sync_bullion_fn, take_snapshot_fn, init_db_fn, goldapi_status_fn=None):
    """Return the Settings blueprint with app-level callbacks injected.

    The callbacks remain in app.py for now because bullion/snapshot extraction is
    a later refactor step. Passing them in avoids importing from app.py and
    prevents circular imports.
    """

    settings_bp = Blueprint("settings", __name__)

    @settings_bp.route("/settings", methods=["GET", "POST"])
    def settings():
        conn = get_db()
        if request.method == "POST":
            set_setting(conn, "manual_gold_gbp_per_g", request.form["manual_gold_gbp_per_g"])
            set_setting(conn, "manual_silver_gbp_per_g", request.form["manual_silver_gbp_per_g"])
            set_setting(conn, "use_live_prices", "1" if request.form.get("use_live_prices") == "on" else "0")
            refresh_mode = request.form.get("goldapi_refresh_mode", "daily")
            if refresh_mode not in {"manual", "12h", "daily"}:
                refresh_mode = "daily"
            set_setting(conn, "goldapi_refresh_mode", refresh_mode)

            new_goldapi_key = request.form.get("goldapi_key", "").strip()
            if request.form.get("clear_goldapi_key") == "on":
                set_setting(conn, "goldapi_key", "")
            elif new_goldapi_key:
                set_setting(conn, "goldapi_key", new_goldapi_key)

            conn.commit()
            sync_bullion_fn(conn)
            take_snapshot_fn(conn)
            flash("Settings saved.")
            conn.close()
            return redirect(url_for("settings.settings"))

        t212_settings = trading212_get_settings(conn)
        t212_logs = conn.execute("SELECT * FROM trading212_sync_log ORDER BY synced_at DESC, id DESC LIMIT 12").fetchall()
        t212_accounts = conn.execute("SELECT * FROM accounts WHERE COALESCE(is_archived, 0) = 0 ORDER BY account_type, name").fetchall()

        saved_goldapi_key = str(get_setting(conn, "goldapi_key", "") or "").strip()
        has_env_goldapi_key = bool(GOLDAPI_KEY)
        goldapi_status = goldapi_status_fn(conn) if goldapi_status_fn else {}
        goldapi_key_source = goldapi_status.get("key_source") or ("Settings" if saved_goldapi_key else (".env fallback" if has_env_goldapi_key else "Not configured"))

        values = {
            "manual_gold_gbp_per_g": get_setting(conn, "manual_gold_gbp_per_g"),
            "manual_silver_gbp_per_g": get_setting(conn, "manual_silver_gbp_per_g"),
            "use_live_prices": get_setting(conn, "use_live_prices") == "1",
            "goldapi_refresh_mode": get_setting(conn, "goldapi_refresh_mode", "daily"),
            "has_goldapi_key": bool(saved_goldapi_key or has_env_goldapi_key),
            "goldapi_saved_key_present": bool(saved_goldapi_key),
            "goldapi_env_key_present": has_env_goldapi_key,
            "goldapi_key_source": goldapi_key_source,
            "goldapi_cache": goldapi_status,
            "t212_settings": t212_settings,
            "t212_logs": t212_logs,
            "t212_accounts": t212_accounts,
            "t212_auto_account_name": TRADING212_AUTO_ACCOUNT_NAME,
            "t212_auto_account_type": TRADING212_AUTO_ACCOUNT_TYPE,
            "t212_credentials_present": trading212_credentials_present(conn),
            "t212_saved_credentials_present": bool(("api_key" in t212_settings.keys() and t212_settings["api_key"]) and ("api_secret" in t212_settings.keys() and t212_settings["api_secret"])),
            "database_path": os.path.relpath(DB_NAME, APP_DIR),
            "database_backups": list_database_backups(),
            "database_undo": get_undo_status(),
        }
        conn.close()
        return render_template("settings.html", **values)

    @settings_bp.route("/settings/goldapi/sync", methods=["POST"])
    def goldapi_sync_now():
        conn = get_db()
        try:
            sync_bullion_fn(conn, force_price_refresh=True)
            take_snapshot_fn(conn)
            if goldapi_status_fn:
                status = goldapi_status_fn(conn)
                flash(status.get("last_message") or "Metal prices synced.")
            else:
                flash("Metal prices synced.")
        except Exception as exc:
            flash(f"GoldAPI sync failed: {exc}")
        finally:
            conn.close()
        return redirect(url_for("settings.settings"))

    @settings_bp.route("/settings/database/backup", methods=["POST"])
    def database_backup():
        backup_path = create_database_backup("manual")
        if backup_path:
            flash(f"Database backup created: {os.path.basename(backup_path)}")
        else:
            flash("No database found to back up yet.")
        return redirect(url_for("settings.settings"))

    @settings_bp.route("/settings/database/import", methods=["POST"])
    def database_import():
        uploaded = request.files.get("database_file")
        if not uploaded or uploaded.filename == "":
            flash("Choose a finance.db file to import.")
            return redirect(url_for("settings.settings"))

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temp_file:
            uploaded.save(temp_file.name)
            temp_path = temp_file.name

        try:
            ok, message = validate_sqlite_database(temp_path)
            if not ok:
                flash(f"Import cancelled. Database integrity check failed: {message}")
                return redirect(url_for("settings.settings"))

            create_database_backup("pre_import")
            replace_current_database(temp_path)
            init_db_fn()
            flash("Database imported successfully. A pre-import backup was created first.")
        except Exception as exc:
            flash(f"Database import failed: {exc}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return redirect(url_for("settings.settings"))

    @settings_bp.route("/settings/database/restore", methods=["POST"])
    def database_restore():
        filename = os.path.basename(request.form.get("backup_filename", ""))
        valid_backups = {item["filename"] for item in list_database_backups()}
        if filename not in valid_backups:
            flash("Select a valid database backup to restore.")
            return redirect(url_for("settings.settings"))

        backup_path = os.path.join(DB_BACKUP_DIR, filename)
        try:
            create_database_backup("pre_restore")
            replace_current_database(backup_path)
            init_db_fn()
            flash(f"Database restored from {filename}. A pre-restore backup was created first.")
        except Exception as exc:
            flash(f"Database restore failed: {exc}")
        return redirect(url_for("settings.settings"))

    @settings_bp.route("/settings/database/undo", methods=["POST"])
    def database_undo():
        points = list_database_undo_points()
        if not points:
            flash("No undo point is available yet.")
            return redirect(url_for("settings.settings"))

        requested = os.path.basename(request.form.get("undo_filename", ""))
        valid_points = {item["filename"]: item for item in points}
        undo_filename = requested if requested in valid_points else points[0]["filename"]
        undo_path = os.path.join(DB_UNDO_DIR, undo_filename)

        try:
            create_database_backup("pre_undo")
            replace_current_database(undo_path)
            init_db_fn()

            # Remove the undo point that was just consumed. The previous four remain
            # available, so a second undo can still step back further if needed.
            for path in (undo_path, os.path.splitext(undo_path)[0] + ".json"):
                if os.path.exists(path):
                    os.remove(path)

            flash(f"Database restored from undo point: {undo_filename}. A pre-undo backup was created first.")
        except Exception as exc:
            flash(f"Undo failed: {exc}")
        return redirect(url_for("settings.settings"))

    @settings_bp.route("/settings/database/download/<path:filename>")
    def database_download_backup(filename):
        filename = os.path.basename(filename)
        valid_backups = {item["filename"] for item in list_database_backups()}
        if filename not in valid_backups:
            flash("Backup not found.")
            return redirect(url_for("settings.settings"))
        return send_file(os.path.join(DB_BACKUP_DIR, filename), as_attachment=True, download_name=filename)

    return settings_bp
