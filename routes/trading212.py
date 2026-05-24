"""Trading 212 route blueprint for InvestHome."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import TRADING212_AUTO_ACCOUNT_NAME
from db import get_db
from services.trading212 import (
    Trading212RateLimitError,
    _first_text,
    trading212_api_get,
    trading212_credentials_present,
    trading212_get_settings,
    trading212_log,
    trading212_reconcile_auto_account_from_cache,
    trading212_sync,
)


def create_trading212_blueprint(take_snapshot_fn, format_money_fn):
    trading212_bp = Blueprint("trading212", __name__)

    @trading212_bp.route("/trading212")
    def trading212_page():
        conn = get_db()
        trading212_reconcile_auto_account_from_cache(conn, snapshot_fn=take_snapshot_fn)
        settings = trading212_get_settings(conn)
        holdings = conn.execute("SELECT * FROM trading212_holdings ORDER BY current_value DESC, ticker").fetchall()
        logs = conn.execute("SELECT * FROM trading212_sync_log ORDER BY synced_at DESC, id DESC LIMIT 10").fetchall()
        accounts = conn.execute("SELECT * FROM accounts WHERE COALESCE(is_archived, 0) = 0 ORDER BY account_type, name").fetchall()
        total_holdings = float(settings["holdings_value"] or 0) if "holdings_value" in settings.keys() else sum(float(row["current_value"] or 0) for row in holdings)
        total_cash = float(settings["cash_value"] or 0) if "cash_value" in settings.keys() else 0
        portfolio_total = float(settings["portfolio_total"] or 0) if "portfolio_total" in settings.keys() else round(total_holdings + total_cash, 2)
        credentials_present = trading212_credentials_present(conn)
        conn.close()
        return render_template(
            "trading212.html",
            settings=settings,
            holdings=holdings,
            logs=logs,
            accounts=accounts,
            total_holdings=round(total_holdings, 2),
            total_cash=round(total_cash, 2),
            portfolio_total=round(portfolio_total, 2),
            credentials_present=credentials_present,
        )

    @trading212_bp.route("/trading212/settings", methods=["POST"])
    def trading212_update_settings():
        environment = request.form.get("environment", "demo")
        if environment not in {"demo", "live"}:
            environment = "demo"
        target_account_name = TRADING212_AUTO_ACCOUNT_NAME
        auto_update_account = 1
        api_key = request.form.get("api_key", "").strip()
        api_secret = request.form.get("api_secret", "").strip()
        conn = get_db()
        conn.execute(
            """
            UPDATE trading212_settings
            SET environment = ?, target_account_name = ?, auto_update_account = ?
            WHERE id = 1
            """,
            (environment, target_account_name, auto_update_account),
        )

        if api_key or api_secret:
            existing = trading212_get_settings(conn)
            saved_api_key = api_key or (existing["api_key"] if "api_key" in existing.keys() else None)
            saved_api_secret = api_secret or (existing["api_secret"] if "api_secret" in existing.keys() else None)
            conn.execute(
                """
                UPDATE trading212_settings
                SET api_key = ?, api_secret = ?, credentials_updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (saved_api_key, saved_api_secret),
            )
            flash("Trading 212 credentials saved. Existing saved credentials were overwritten.")

        conn.commit()
        conn.close()
        flash("Trading 212 settings updated.")
        return redirect(url_for("settings.settings"))

    @trading212_bp.route("/trading212/test", methods=["POST"])
    def trading212_test_connection():
        conn = get_db()
        settings = trading212_get_settings(conn)
        try:
            summary = trading212_api_get(settings["environment"], "/equity/account/summary", conn)
            currency = _first_text(summary, ["currency", "accountCurrency", "baseCurrency"], "unknown currency")
            trading212_log(conn, "success", f"Connection test passed. Account currency: {currency}.")
            flash("Trading 212 connection test passed.")
        except Trading212RateLimitError as exc:
            conn.execute("UPDATE trading212_settings SET rate_limit_reset_at = ? WHERE id = 1", (exc.reset_at,))
            trading212_log(conn, "error", f"Connection test rate limited: {exc}")
            flash(str(exc))
        except Exception as exc:
            trading212_log(conn, "error", f"Connection test failed: {exc}")
            flash(f"Trading 212 connection test failed: {exc}")
        finally:
            conn.close()
        return redirect(url_for("settings.settings"))

    @trading212_bp.route("/trading212/sync", methods=["POST"])
    def trading212_sync_now():
        conn = get_db()
        try:
            result = trading212_sync(conn, snapshot_fn=take_snapshot_fn)
            flash(f"Trading 212 sync complete. Portfolio value: {format_money_fn(result['portfolio_total'])}.")
        except Trading212RateLimitError as exc:
            conn.execute("UPDATE trading212_settings SET rate_limit_reset_at = ? WHERE id = 1", (exc.reset_at,))
            trading212_log(conn, "error", f"Sync rate limited: {exc}")
            flash(str(exc))
        except Exception as exc:
            trading212_log(conn, "error", f"Sync failed: {exc}")
            flash(f"Trading 212 sync failed: {exc}")
        finally:
            conn.close()
        return redirect(url_for("settings.settings"))

    return trading212_bp
