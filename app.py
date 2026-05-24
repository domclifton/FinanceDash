import base64
import csv
import io
import json
import os
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, url_for

load_dotenv()

from config import (
    ACCOUNT_TYPES,
    APP_DIR,
    APP_VERSION,
    DATA_DIR,
    DB_BACKUP_DIR,
    DB_NAME,
    DB_UNDO_DIR,
    DEBT_TYPES,
    GOLDAPI_KEY,
    LEGACY_DB_NAME,
    MAX_DATABASE_BACKUPS,
    MAX_DATABASE_UNDO_POINTS,
    TERM_TYPES,
    TRADING212_AUTO_ACCOUNT_NAME,
    TRADING212_AUTO_ACCOUNT_TYPE,
    TRADING212_AUTO_TERM_TYPE,
    TRADING212_PROVIDER,
)

from db import default_term_for_account, get_account_types, get_db, get_setting, init_db as run_database_migrations, set_setting

from services.backups import (
    ensure_database_storage,
    save_undo_point,
)
from services.trading212 import (
    Trading212RateLimitError,
    _first_text,
    is_auto_managed_account,
    is_trading212_auto_account,
    normalise_trading212_money,
    trading212_api_get,
    trading212_credentials_present,
    trading212_get_settings,
    trading212_log,
    trading212_reconcile_auto_account_from_cache,
    trading212_sync,
)

from services.performance import (
    _nice_axis_max,
    monthly_performance,
    performance_chart_series,
    performance_rows,
)
from services.debts import debt_summary, normalise_debt_type
from routes.settings import create_settings_blueprint
from routes.debts import debts_bp
from routes.progress import create_progress_blueprint
from routes.accounts import create_accounts_blueprint
from routes.budget import budget_bp
from routes.property import property_bp
from routes.trading212 import create_trading212_blueprint
from utils import safe_float


ensure_database_storage()

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-change-me")


@app.before_request
def create_database_undo_point():
    """Capture the DB before user POST actions so Settings can undo recent actions."""
    skip_endpoints = {
        "settings.database_backup",
        "settings.database_download_backup",
        "settings.database_undo",
    }
    if request.method != "POST" or request.endpoint in skip_endpoints:
        return
    try:
        save_undo_point(request.endpoint or request.path)
    except Exception:
        # Undo support should never block the app from accepting a normal action.
        pass


@app.context_processor
def inject_app_version():
    last_snapshot_date = None
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM settings WHERE key = 'last_snapshot_date'").fetchone()
        last_snapshot_date = row["value"] if row else None
        conn.close()
    except Exception:
        last_snapshot_date = None
    return {"app_version": APP_VERSION, "last_snapshot_date": last_snapshot_date}


def format_money(value, decimals=2, symbol=True):
    """Format money with thousands separators, e.g. £1,234,567.89."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0

    sign = "-" if number < 0 else ""
    formatted = f"{abs(number):,.{decimals}f}"
    return f"{sign}£{formatted}" if symbol else f"{sign}{formatted}"


@app.template_filter("money")
def money_filter(value):
    return format_money(value)


@app.template_filter("money4")
def money4_filter(value):
    return format_money(value, decimals=4)


def is_lifetime_isa(account):
    """Return True for Lifetime ISA accounts by name or category.

    Lifetime ISA deposits are recorded at the actual deposited amount only.
    The 25% government bonus is not added automatically because it can arrive
    weeks later. When the bonus appears in the provider account, update the
    account total value so it is recorded as a real value change/growth.
    """
    name = str(account["name"] or "").lower()
    account_type = str(account["account_type"] or "").lower()
    return "lifetime isa" in name or "lisa" == name.strip() or "lifetime isa" in account_type


def get_goldapi_key(conn=None):
    """Return the Settings-stored GoldAPI key, falling back to .env if needed."""
    stored_key = ""
    if conn is not None:
        stored_key = str(get_setting(conn, "goldapi_key", "") or "").strip()
    return stored_key or GOLDAPI_KEY


def _parse_setting_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_goldapi_timestamp(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _goldapi_refresh_hours(conn):
    mode = str(get_setting(conn, "goldapi_refresh_mode", "daily") or "daily").lower()
    if mode == "12h":
        return 12
    if mode == "daily":
        return 24
    return None


def goldapi_cache_status(conn):
    """Return cached GoldAPI state for Settings and sync decisions."""
    last_sync_at = get_setting(conn, "goldapi_last_sync_at", "")
    last_dt = _parse_goldapi_timestamp(last_sync_at)
    refresh_mode = str(get_setting(conn, "goldapi_refresh_mode", "daily") or "daily").lower()
    if refresh_mode not in {"manual", "12h", "daily"}:
        refresh_mode = "daily"

    refresh_hours = _goldapi_refresh_hours(conn)
    next_sync_at = "Manual only"
    is_due = False
    if refresh_hours is not None:
        if last_dt:
            next_dt = last_dt + timedelta(hours=refresh_hours)
            next_sync_at = next_dt.strftime("%Y-%m-%d %H:%M")
            is_due = datetime.now() >= next_dt
        else:
            next_sync_at = "On next app use"
            is_due = True

    cached_gold = _parse_setting_float(get_setting(conn, "goldapi_cached_gold_gbp_per_g", ""), None)
    cached_silver = _parse_setting_float(get_setting(conn, "goldapi_cached_silver_gbp_per_g", ""), None)
    has_cache = cached_gold is not None and cached_silver is not None

    saved_key = str(get_setting(conn, "goldapi_key", "") or "").strip()
    has_env_key = bool(GOLDAPI_KEY)
    key_source = "Settings" if saved_key else (".env fallback" if has_env_key else "Not configured")

    return {
        "refresh_mode": refresh_mode,
        "refresh_label": {"manual": "Manual only", "12h": "Every 12 hours", "daily": "Daily"}.get(refresh_mode, "Daily"),
        "last_sync_at": last_sync_at or "Never",
        "next_sync_at": next_sync_at,
        "is_due": is_due,
        "has_cache": has_cache,
        "cached_gold": cached_gold,
        "cached_silver": cached_silver,
        "last_status": get_setting(conn, "goldapi_last_status", "Not synced"),
        "last_message": get_setting(conn, "goldapi_last_message", "No GoldAPI sync has run yet."),
        "key_source": key_source,
        "has_key": bool(saved_key or has_env_key),
        "saved_key_present": bool(saved_key),
        "env_key_present": has_env_key,
    }


def fetch_goldapi_price_per_gram(symbol, api_key=None):
    api_key = str(api_key or "").strip()
    if not api_key:
        return None

    url = f"https://www.goldapi.io/api/{symbol}/GBP"
    headers = {"x-access-token": api_key, "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()
        price_per_ounce = float(data["price"])
        return round(price_per_ounce / 31.1035, 4)
    except Exception as exc:
        print(f"GoldAPI fetch failed for {symbol}: {exc}")
        return None


def refresh_goldapi_price_cache(conn, force=False):
    """Refresh cached metal prices only when due or explicitly forced.

    Page loads should normally read the cache. This prevents Dashboard, Accounts,
    Bullion and automatic snapshot requests from repeatedly calling GoldAPI.
    """
    use_live = get_setting(conn, "use_live_prices", "1") == "1"
    status = goldapi_cache_status(conn)
    if not use_live:
        set_setting(conn, "goldapi_last_status", "disabled")
        set_setting(conn, "goldapi_last_message", "Live pricing is switched off; manual prices are being used.")
        conn.commit()
        return {**status, "refreshed": False, "status": "disabled", "message": "Live pricing is switched off."}

    goldapi_key = get_goldapi_key(conn)
    if not goldapi_key:
        set_setting(conn, "goldapi_last_status", "missing_key")
        set_setting(conn, "goldapi_last_message", "GoldAPI key is not configured.")
        conn.commit()
        return {**status, "refreshed": False, "status": "missing_key", "message": "GoldAPI key is not configured."}

    should_refresh = bool(force)
    if not should_refresh and status["refresh_mode"] != "manual":
        should_refresh = (not status["has_cache"]) or status["is_due"]

    if not should_refresh:
        return {**status, "refreshed": False, "status": "cached", "message": "Using cached GoldAPI prices."}

    gold_live = fetch_goldapi_price_per_gram("XAU", api_key=goldapi_key)
    silver_live = fetch_goldapi_price_per_gram("XAG", api_key=goldapi_key)
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")

    if gold_live is not None:
        set_setting(conn, "goldapi_cached_gold_gbp_per_g", f"{gold_live:.4f}")
    if silver_live is not None:
        set_setting(conn, "goldapi_cached_silver_gbp_per_g", f"{silver_live:.4f}")

    if gold_live is not None or silver_live is not None:
        set_setting(conn, "goldapi_last_sync_at", now)
        set_setting(conn, "goldapi_last_status", "success" if gold_live is not None and silver_live is not None else "partial")
        message = "GoldAPI prices refreshed." if gold_live is not None and silver_live is not None else "GoldAPI partially refreshed; using cached/manual fallback for the missing metal."
        set_setting(conn, "goldapi_last_message", message)
        conn.commit()
        return {**goldapi_cache_status(conn), "refreshed": True, "status": "success", "message": message}

    set_setting(conn, "goldapi_last_status", "failed")
    set_setting(conn, "goldapi_last_message", "GoldAPI refresh failed; cached/manual prices are being used.")
    conn.commit()
    return {**goldapi_cache_status(conn), "refreshed": False, "status": "failed", "message": "GoldAPI refresh failed; cached/manual prices are being used."}


def get_metal_prices(conn, force_refresh=False):
    manual_gold = float(get_setting(conn, "manual_gold_gbp_per_g", "60"))
    manual_silver = float(get_setting(conn, "manual_silver_gbp_per_g", "0.75"))
    use_live = get_setting(conn, "use_live_prices", "1") == "1"

    if use_live:
        refresh_goldapi_price_cache(conn, force=force_refresh)

    cached_gold = _parse_setting_float(get_setting(conn, "goldapi_cached_gold_gbp_per_g", ""), None)
    cached_silver = _parse_setting_float(get_setting(conn, "goldapi_cached_silver_gbp_per_g", ""), None)

    gold_value = cached_gold if use_live and cached_gold is not None else manual_gold
    silver_value = cached_silver if use_live and cached_silver is not None else manual_silver

    return {
        "Gold": gold_value,
        "Silver": silver_value,
        "gold_source": "Cached live" if use_live and cached_gold is not None else "Manual fallback",
        "silver_source": "Cached live" if use_live and cached_silver is not None else "Manual fallback",
    }


def bullion_rows_with_values(conn, force_price_refresh=False):
    prices = get_metal_prices(conn, force_refresh=force_price_refresh)
    rows = conn.execute("SELECT * FROM bullion ORDER BY metal, name").fetchall()
    output = []
    total_value = 0.0
    total_cost = 0.0

    for row in rows:
        price = prices[row["metal"]]
        pure_grams = row["weight_grams"] * row["purity"] * row["quantity"]
        current_value = pure_grams * price
        purchase_price = float(row["purchase_price"] or 0)
        profit_loss = current_value - purchase_price
        total_value += current_value
        total_cost += purchase_price
        output.append({
            **dict(row),
            "pure_grams": round(pure_grams, 3),
            "current_value": round(current_value, 2),
            "profit_loss": round(profit_loss, 2),
            "price_per_gram": round(price, 4),
        })

    return output, round(total_value, 2), round(total_cost, 2), prices


def sync_bullion_account(conn, force_price_refresh=False):
    items, total_value, _total_cost, _prices = bullion_rows_with_values(conn, force_price_refresh=force_price_refresh)
    conn.execute(
        "UPDATE accounts SET current_value = ? WHERE account_type = 'Physical Bullion'",
        (total_value,),
    )
    conn.commit()
    return total_value


def take_snapshot(conn):
    today = date.today().isoformat()
    accounts = conn.execute("SELECT id, current_value FROM accounts WHERE COALESCE(is_archived, 0) = 0").fetchall()
    for account in accounts:
        conn.execute(
            """
            INSERT INTO snapshots (account_id, value, snapshot_date)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, snapshot_date) DO UPDATE SET value = excluded.value
            """,
            (account["id"], account["current_value"], today),
        )
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('last_snapshot_date', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (today,),
    )
    conn.commit()



def init_db():
    """Run database schema setup while preserving app-level post-init behaviour."""
    run_database_migrations(
        sync_bullion_fn=sync_bullion_account,
        take_snapshot_fn=take_snapshot,
    )


app.register_blueprint(create_settings_blueprint(sync_bullion_account, take_snapshot, init_db, goldapi_cache_status))
app.register_blueprint(debts_bp)
app.register_blueprint(budget_bp)
app.register_blueprint(property_bp)
app.register_blueprint(create_accounts_blueprint(take_snapshot, sync_bullion_account, is_lifetime_isa, format_money))
app.register_blueprint(create_trading212_blueprint(take_snapshot, format_money))


def ensure_daily_snapshot():
    """Automatically take one snapshot per day when the app is opened."""
    if request.endpoint in {"static"}:
        return

    conn = get_db()
    today = date.today().isoformat()
    last_auto = get_setting(conn, "last_auto_snapshot_date")

    if last_auto != today:
        sync_bullion_account(conn)
        take_snapshot(conn)
        set_setting(conn, "last_auto_snapshot_date", today)
        conn.commit()

    conn.close()


app.before_request(ensure_daily_snapshot)




def compound_projection(starting_value, annual_rate_pct, years, months, monthly_contribution=0, annual_contribution_increase_pct=0):
    """Monthly compound projection with optional monthly deposits and yearly deposit increase."""
    total_months = max(0, int(years) * 12 + int(months))
    monthly_rate = (float(annual_rate_pct) / 100) / 12
    balance = float(starting_value or 0)
    contribution = float(monthly_contribution or 0)
    increase_rate = float(annual_contribution_increase_pct or 0) / 100
    total_contributed = 0.0
    points = []

    for month in range(1, total_months + 1):
        if month > 1 and (month - 1) % 12 == 0:
            contribution *= (1 + increase_rate)
        balance += contribution
        total_contributed += contribution
        balance *= (1 + monthly_rate)
        if month % 12 == 0 or month == total_months:
            points.append({
                "month": month,
                "year_label": f"Year {month // 12}" if month % 12 == 0 else f"Month {month}",
                "value": round(balance, 2),
            })

    growth = balance - float(starting_value or 0) - total_contributed
    return {
        "future_value": round(balance, 2),
        "starting_value": round(float(starting_value or 0), 2),
        "total_contributed": round(total_contributed, 2),
        "growth": round(growth, 2),
        "points": points,
    }


def compound_accounts(conn):
    """Return active investment/pension accounts for compound projections.

    Intentionally exclude archived accounts and zero-value placeholder rows so
    deleted/default accounts do not keep reappearing in the Monthly
    Contributions section or affect projection figures.
    """
    return conn.execute(
        """
        SELECT * FROM accounts
        WHERE COALESCE(is_archived, 0) = 0
          AND include_in_net_worth = 1
          AND COALESCE(term_type, '') != 'Ignore'
          AND COALESCE(current_value, 0) > 0
          AND (
              account_type IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
              OR name IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
          )
        ORDER BY CASE
            WHEN account_type = 'Pension' OR name = 'Pension' THEN 1
            WHEN account_type = 'Lifetime ISA' OR name = 'Lifetime ISA' THEN 2
            WHEN account_type = 'Stocks and Shares ISA' OR name = 'Stocks and Shares ISA' THEN 3
            ELSE 4
        END, name
        """
    ).fetchall()

def bucket_account_names(accounts, term_type, max_names=4):
    """Return a compact list of account names assigned to a dashboard Type bucket."""
    names = [str(a["name"] or "").strip() for a in accounts if a["term_type"] == term_type and str(a["name"] or "").strip()]
    if not names:
        return "No accounts selected"
    if len(names) > max_names:
        shown = ", ".join(names[:max_names])
        return f"{shown} +{len(names) - max_names} more"
    return ", ".join(names)


def pension_account_names(conn, max_names=4):
    """Return a compact list of pension accounts shown in the dashboard Pension bucket."""
    rows = conn.execute("""
        SELECT name FROM accounts
        WHERE include_in_net_worth = 1
          AND COALESCE(is_archived, 0) = 0
          AND account_type = 'Pension'
          AND COALESCE(term_type, '') != 'Ignore'
        ORDER BY name
    """).fetchall()
    names = [str(row["name"] or "").strip() for row in rows if str(row["name"] or "").strip()]
    if not names:
        return "No pension accounts selected"
    if len(names) > max_names:
        shown = ", ".join(names[:max_names])
        return f"{shown} +{len(names) - max_names} more"
    return ", ".join(names)



def clamp_percent(current, target):
    current = safe_float(current)
    target = safe_float(target)
    if target <= 0:
        return 100 if current > 0 else 0
    return max(0, min(100, round((current / target) * 100)))



def progress_bar_width(value):
    return max(0, min(100, int(round(safe_float(value)))))


def next_money_milestone(value):
    value = safe_float(value)
    milestones = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000]
    for milestone in milestones:
        if value < milestone:
            previous = 0
            for candidate in milestones:
                if candidate < milestone:
                    previous = candidate
                else:
                    break
            progress_base = max(value - previous, 0)
            progress_range = max(milestone - previous, 1)
            return {
                "current": value,
                "target": milestone,
                "previous": previous,
                "percent": max(0, min(100, round((progress_base / progress_range) * 100))),
            }
    return {"current": value, "target": value, "previous": value, "percent": 100}


def progress_setting_float(conn, key, default):
    return safe_float(get_setting(conn, key, default), default)


def current_month_contributions(conn):
    month = date.today().strftime("%Y-%m")
    row = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0) AS total
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.transaction_type IN ('add', 'remove')
          AND substr(t.created_at, 1, 7) = ?
          AND COALESCE(a.is_archived, 0) = 0
          AND COALESCE(a.include_in_net_worth, 1) = 1
          AND COALESCE(a.term_type, '') != 'Ignore'
        """,
        (month,),
    ).fetchone()
    return round(float(row["total"] or 0), 2) if row else 0.0


def savings_streak_months(conn):
    rows = conn.execute(
        """
        SELECT substr(t.created_at, 1, 7) AS month,
               COALESCE(SUM(t.amount), 0) AS total
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.transaction_type IN ('add', 'remove')
          AND COALESCE(a.is_archived, 0) = 0
          AND COALESCE(a.include_in_net_worth, 1) = 1
          AND COALESCE(a.term_type, '') != 'Ignore'
        GROUP BY substr(t.created_at, 1, 7)
        """
    ).fetchall()
    totals = {row["month"]: float(row["total"] or 0) for row in rows if row["month"]}
    if not totals:
        return 0

    streak = 0
    cursor = date.today().replace(day=1)
    for _ in range(120):
        key = cursor.strftime("%Y-%m")
        if totals.get(key, 0) > 0:
            streak += 1
            cursor = (cursor - timedelta(days=1)).replace(day=1)
        else:
            break
    return streak


def first_existing(*values):
    for value in values:
        if safe_float(value, 0) > 0:
            return safe_float(value)
    return 0.0


def build_badge(icon, title, description, current, target, unit="money"):
    current = safe_float(current)
    target = safe_float(target)
    pct = clamp_percent(current, target)
    if unit == "count":
        progress_text = f"{int(current):,} / {int(target):,}"
    elif unit == "percent":
        progress_text = f"{current:.1f}% / {target:.1f}%"
    else:
        progress_text = f"{format_money(current)} / {format_money(target)}"
    return {
        "icon": icon,
        "title": title,
        "description": description,
        "current": current,
        "target": target,
        "percent": pct,
        "progress_text": progress_text,
        "unlocked": current >= target if target > 0 else current > 0,
    }


def progress_payload(conn):
    """Build the first-draft gamified Progress page from existing local data."""
    dashboard = dashboard_payload(conn)
    total_net_worth = safe_float(dashboard.get("total_all_assets"))
    emergency_total = safe_float(dashboard.get("emergency"))
    short_term_total = safe_float(dashboard.get("short_term"))
    liquid_total = safe_float(dashboard.get("liquid"))
    pension_total = safe_float(dashboard.get("pension"))
    total_debt = safe_float(dashboard.get("total_debt"))
    debt_count = int(dashboard.get("debt_count") or 0)

    investment_row = conn.execute(
        """
        SELECT COALESCE(SUM(current_value), 0) AS total
        FROM accounts
        WHERE COALESCE(is_archived, 0) = 0
          AND COALESCE(include_in_net_worth, 1) = 1
          AND COALESCE(term_type, '') != 'Ignore'
          AND account_type IN ('Stocks and Shares ISA', 'Lifetime ISA')
        """
    ).fetchone()
    investment_total = safe_float(investment_row["total"] if investment_row else 0)

    solo_income = safe_float(dashboard.get("solo_income"))
    solo_left = safe_float(dashboard.get("solo_left"))
    couple_income = safe_float(dashboard.get("couple_income"))
    couple_left = safe_float(dashboard.get("couple_left"))
    budget_income = first_existing(couple_income, solo_income)
    budget_left = couple_left if couple_income > 0 else solo_left
    derived_monthly_spend = max(budget_income - budget_left, 0) if budget_income else 0

    monthly_expenses = progress_setting_float(conn, "progress_monthly_expenses", derived_monthly_spend)
    if monthly_expenses <= 0:
        # First-run fallback so emergency levels and badges are useful before budgets are configured.
        monthly_expenses = 1000
    monthly_savings_goal = progress_setting_float(conn, "progress_monthly_savings_goal", 500)
    uk_net_worth_benchmark = progress_setting_float(conn, "progress_uk_net_worth_benchmark", 293700)
    uk_savings_rate_benchmark = progress_setting_float(conn, "progress_uk_savings_rate_benchmark", 10)

    saved_this_month = current_month_contributions(conn)
    savings_rate = round((saved_this_month / budget_income) * 100, 1) if budget_income > 0 else 0.0
    streak = savings_streak_months(conn)

    milestone = next_money_milestone(total_net_worth)
    emergency_levels = [
        {"level": 1, "name": "Starter Buffer", "target": 1000},
        {"level": 2, "name": "1 Month Covered", "target": monthly_expenses * 1 if monthly_expenses else 0},
        {"level": 3, "name": "3 Months Covered", "target": monthly_expenses * 3 if monthly_expenses else 0},
        {"level": 4, "name": "6 Months Covered", "target": monthly_expenses * 6 if monthly_expenses else 0},
        {"level": 5, "name": "12 Months Covered", "target": monthly_expenses * 12 if monthly_expenses else 0},
    ]
    highest_level = 0
    current_level = emergency_levels[0]
    next_level = emergency_levels[0]
    for level in emergency_levels:
        if level["target"] and emergency_total >= level["target"]:
            highest_level = level["level"]
            current_level = level
        elif level["target"]:
            next_level = level
            break
    else:
        next_level = emergency_levels[-1]

    emergency_next_pct = clamp_percent(emergency_total, next_level["target"])
    challenge_pct = clamp_percent(saved_this_month, monthly_savings_goal)

    levels = [
        {
            "label": "Emergency Fund",
            "level": highest_level,
            "max_level": 5,
            "value": emergency_total,
            "target": next_level["target"],
            "detail": f"Next: {next_level['name']}" if highest_level < 5 else "Max emergency level reached",
            "percent": emergency_next_pct if highest_level < 5 else 100,
        },
        {
            "label": "Investing",
            "level": 1 + int(investment_total >= 1000) + int(investment_total >= 5000) + int(investment_total >= 10000) + int(investment_total >= 25000),
            "max_level": 5,
            "value": investment_total,
            "target": 25000,
            "detail": "Stocks and Shares ISA + Lifetime ISA",
            "percent": clamp_percent(investment_total, 25000),
        },
        {
            "label": "Pension",
            "level": 1 + int(pension_total >= 10000) + int(pension_total >= 25000) + int(pension_total >= 50000) + int(pension_total >= 100000),
            "max_level": 5,
            "value": pension_total,
            "target": 100000,
            "detail": dashboard.get("pension_accounts", "Pension accounts"),
            "percent": clamp_percent(pension_total, 100000),
        },
        {
            "label": "Budgeting",
            "level": 1 + int(budget_left > 0) + int(streak >= 2) + int(streak >= 4) + int(streak >= 6),
            "max_level": 5,
            "value": max(budget_left, 0),
            "target": monthly_savings_goal,
            "detail": f"{streak} month saving streak",
            "percent": clamp_percent(streak, 6),
        },
        {
            "label": "Debt Control",
            "level": 5 if total_debt <= 0 else max(1, 5 - int(total_debt >= 1000) - int(total_debt >= 5000) - int(total_debt >= 10000) - int(total_debt >= 25000)),
            "max_level": 5,
            "value": total_debt,
            "target": 0,
            "detail": "No included debts" if total_debt <= 0 else f"{debt_count} included debt account(s)",
            "percent": 100 if total_debt <= 0 else max(5, 100 - clamp_percent(total_debt, 25000)),
        },
    ]

    badges = [
        build_badge("🏦", "First £1,000 Saved", "Starter savings buffer reached", emergency_total + liquid_total + short_term_total, 1000),
        build_badge("🛡️", "3 Month Emergency Fund", "Three months of spending protected", emergency_total, monthly_expenses * 3 if monthly_expenses else 1),
        build_badge("🏰", "6 Month Shield", "Six months of spending protected", emergency_total, monthly_expenses * 6 if monthly_expenses else 1),
        build_badge("📈", "Investor Level 1", "First £1,000 invested", investment_total, 1000),
        build_badge("🚀", "Investment Builder", "£10,000 invested", investment_total, 10000),
        build_badge("♟️", "Pension Builder", "Pension balance over £25,000", pension_total, 25000),
        build_badge("💷", "£50k Net Worth", "Total net worth milestone", total_net_worth, 50000),
        build_badge("🏆", "£100k Net Worth", "Six-figure net worth milestone", total_net_worth, 100000),
        build_badge("🔥", "3 Month Streak", "Positive saving for three months", streak, 3, unit="count"),
        build_badge("⭐", "6 Month Streak", "Positive saving for six months", streak, 6, unit="count"),
        build_badge("🧾", "Debt Tracker", "At least one debt or liability is being tracked", debt_count, 1, unit="count"),
        build_badge("🕊", "Debt Free", "No included debts currently reduce net worth", 1 if total_debt <= 0 else 0, 1, unit="count"),
    ]
    unlocked_badges = [badge for badge in badges if badge["unlocked"]]
    in_progress_badges = [badge for badge in badges if not badge["unlocked"]]

    debt_score = 100 if total_debt <= 0 else max(0, 100 - clamp_percent(total_debt, 25000))
    score_parts = [
        min(clamp_percent(total_net_worth, milestone["target"]), 100) * 0.22,
        min(clamp_percent(emergency_total, monthly_expenses * 6 if monthly_expenses else 1000), 100) * 0.22,
        min(challenge_pct, 100) * 0.18,
        min(clamp_percent(pension_total, 50000), 100) * 0.14,
        min(clamp_percent(streak, 6), 100) * 0.14,
        debt_score * 0.10,
    ]
    progress_score = int(round(sum(score_parts)))

    benchmark_cards = [
        {
            "title": "Net Worth Benchmark",
            "your_value": format_money(total_net_worth),
            "benchmark": format_money(uk_net_worth_benchmark),
            "caption": "Static/configurable UK household wealth benchmark",
            "percent": clamp_percent(total_net_worth, uk_net_worth_benchmark),
        },
        {
            "title": "Savings Rate Benchmark",
            "your_value": f"{savings_rate:.1f}%",
            "benchmark": f"{uk_savings_rate_benchmark:.1f}%",
            "caption": "Configurable UK household saving ratio benchmark",
            "percent": clamp_percent(savings_rate, uk_savings_rate_benchmark),
        },
        {
            "title": "Emergency Coverage",
            "your_value": format_money(emergency_total),
            "benchmark": f"{monthly_expenses and round(emergency_total / monthly_expenses, 1) or 0} months",
            "caption": "Emergency bucket divided by monthly expenses",
            "percent": clamp_percent(emergency_total, monthly_expenses * 6 if monthly_expenses else 1000),
        },
    ]

    return {
        "dashboard": dashboard,
        "progress_score": progress_score,
        "total_net_worth": round(total_net_worth, 2),
        "milestone": milestone,
        "emergency_total": round(emergency_total, 2),
        "emergency_level": highest_level,
        "emergency_next": next_level,
        "emergency_next_pct": emergency_next_pct,
        "savings_streak": streak,
        "saved_this_month": saved_this_month,
        "savings_rate": savings_rate,
        "monthly_expenses": round(monthly_expenses, 2),
        "monthly_savings_goal": round(monthly_savings_goal, 2),
        "challenge_pct": challenge_pct,
        "uk_net_worth_benchmark": round(uk_net_worth_benchmark, 2),
        "uk_savings_rate_benchmark": round(uk_savings_rate_benchmark, 2),
        "levels": levels,
        "badges": badges,
        "unlocked_badges": unlocked_badges,
        "in_progress_badges": in_progress_badges,
        "benchmark_cards": benchmark_cards,
    }


app.register_blueprint(create_progress_blueprint(progress_payload))


def dashboard_payload(conn):
    trading212_reconcile_auto_account_from_cache(conn, snapshot_fn=take_snapshot)
    sync_bullion_account(conn)
    accounts = conn.execute("""
        SELECT * FROM accounts
        WHERE include_in_net_worth = 1
          AND COALESCE(is_archived, 0) = 0
          AND account_type != 'Pension'
          AND COALESCE(term_type, '') != 'Ignore'
        ORDER BY account_type
    """).fetchall()
    total = sum(a["current_value"] for a in accounts)

    # Main-dashboard buckets are driven by the editable term_type dropdown on Accounts.
    # Accounts marked as Ignore are excluded from dashboard statistics and charts.
    emergency = sum(a["current_value"] for a in accounts if a["term_type"] == "Emergency")
    liquid = sum(a["current_value"] for a in accounts if a["term_type"] == "Liquid")
    short_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Short Term")
    mid_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Mid Term")
    long_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Long Term")
    pension = conn.execute("""
        SELECT COALESCE(SUM(current_value), 0) AS total
        FROM accounts
        WHERE include_in_net_worth = 1
          AND COALESCE(is_archived, 0) = 0
          AND account_type = 'Pension'
          AND COALESCE(term_type, '') != 'Ignore'
    """).fetchone()["total"]

    property_row = conn.execute("SELECT home_value, mortgage_left, include_in_net_worth FROM property_settings WHERE id = 1").fetchone()
    property_home_value = float(property_row["home_value"] or 0) if property_row else 0.0
    property_mortgage_left = float(property_row["mortgage_left"] or 0) if property_row else 0.0
    property_include_in_net_worth = bool(int(property_row["include_in_net_worth"] or 0)) if property_row and "include_in_net_worth" in property_row.keys() else True
    property_equity = max(property_home_value - property_mortgage_left, 0)
    property_equity_for_totals = property_equity if property_include_in_net_worth else 0
    mortgage_ltv = round((property_mortgage_left / property_home_value) * 100, 2) if property_home_value else 0

    total_assets_before_debt = total + float(pension or 0) + property_equity_for_totals
    debt_info = debt_summary(conn)
    total_debt = float(debt_info["total_debt"] or 0)
    total_all_assets = total_assets_before_debt - total_debt

    # Allocation chart includes all positive high-level asset buckets.
    category = {
        "Emergency": emergency,
        "Liquid": liquid,
        "Short Term": short_term,
        "Mid Term": mid_term,
        "Long Term": long_term,
        "Pension": float(pension or 0),
        "Property Equity": property_equity_for_totals,
    }
    category = {k: v for k, v in category.items() if v and v > 0}

    snapshots = conn.execute(
        """
        SELECT s.snapshot_date, SUM(s.value) AS total
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        WHERE COALESCE(a.is_archived, 0) = 0
          AND COALESCE(a.include_in_net_worth, 1) = 1
          AND COALESCE(a.term_type, '') != 'Ignore'
        GROUP BY s.snapshot_date
        ORDER BY s.snapshot_date
        """
    ).fetchall()

    recent = conn.execute(
        """
        SELECT t.*, a.name AS account_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE COALESCE(a.term_type, '') != 'Ignore'
          AND COALESCE(a.is_archived, 0) = 0
        ORDER BY t.created_at DESC
        LIMIT 6
        """
    ).fetchall()

    perf_rows, perf_summary = performance_rows(conn, pension_only=False, sync_bullion_fn=sync_bullion_account)

    # Budget snapshots
    solo_income_row = conn.execute("SELECT income FROM budget_settings WHERE id = 1").fetchone()
    solo_income = float(solo_income_row["income"] or 0) if solo_income_row else 0.0
    solo_spend = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM budget_items").fetchone()["total"] or 0
    solo_left = solo_income - float(solo_spend)

    couple_row = conn.execute("SELECT person_one_income, person_two_income FROM couple_budget_settings WHERE id = 1").fetchone()
    couple_income = 0.0
    if couple_row:
        couple_income = float(couple_row["person_one_income"] or 0) + float(couple_row["person_two_income"] or 0)
    couple_spend = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM couple_budget_items").fetchone()["total"] or 0
    couple_left = couple_income - float(couple_spend)

    # Bullion summary
    bullion_items, bullion_total, _bullion_cost, _metal_prices = bullion_rows_with_values(conn)
    bullion_gold = sum(float(i["current_value"] or 0) for i in bullion_items if i["metal"] == "Gold")
    bullion_silver = sum(float(i["current_value"] or 0) for i in bullion_items if i["metal"] == "Silver")

    # Trading 212 cached sync summary
    trading212_settings = trading212_get_settings(conn)
    t212_holdings_value = float(trading212_settings["holdings_value"] or 0) if "holdings_value" in trading212_settings.keys() else 0.0
    t212_cash_value = float(trading212_settings["cash_value"] or 0) if "cash_value" in trading212_settings.keys() else 0.0
    t212_total = float(trading212_settings["portfolio_total"] or 0) if "portfolio_total" in trading212_settings.keys() else round(t212_holdings_value + t212_cash_value, 2)

    return {
        "accounts": accounts,
        "total": round(total, 2),
        "emergency": round(emergency, 2),
        "liquid": round(liquid, 2),
        "short_term": round(short_term, 2),
        "mid_term": round(mid_term, 2),
        "long_term": round(long_term, 2),
        "liquid_accounts": bucket_account_names(accounts, "Liquid"),
        "emergency_accounts": bucket_account_names(accounts, "Emergency"),
        "short_term_accounts": bucket_account_names(accounts, "Short Term"),
        "mid_term_accounts": bucket_account_names(accounts, "Mid Term"),
        "long_term_accounts": bucket_account_names(accounts, "Long Term"),
        "pension": round(pension, 2),
        "pension_accounts": pension_account_names(conn),
        "property_home_value": round(property_home_value, 2),
        "property_mortgage_left": round(property_mortgage_left, 2),
        "property_equity": round(property_equity, 2),
        "property_include_in_net_worth": property_include_in_net_worth,
        "mortgage_ltv": mortgage_ltv,
        "total_assets_before_debt": round(total_assets_before_debt, 2),
        "total_debt": round(total_debt, 2),
        "debt_count": debt_info["debt_count"],
        "total_all_assets": round(total_all_assets, 2),
        "category_labels": json.dumps(list(category.keys())),
        "category_data": json.dumps([round(v, 2) for v in category.values()]),
        "labels": json.dumps([s["snapshot_date"] for s in snapshots]),
        "networth_data": json.dumps([round(float(s["total"] or 0) - total_debt, 2) for s in snapshots]),
        "recent_transactions": recent,
        "performance_rows": perf_rows,
        "total_contributions": perf_summary["total_contributions"],
        "total_growth": perf_summary["total_growth"],
        "total_growth_pct": perf_summary["total_growth_pct"],
        "solo_income": round(solo_income, 2),
        "solo_left": round(solo_left, 2),
        "couple_income": round(couple_income, 2),
        "couple_left": round(couple_left, 2),
        "bullion_total": round(bullion_total, 2),
        "bullion_gold": round(bullion_gold, 2),
        "bullion_silver": round(bullion_silver, 2),
        "t212_holdings_value": round(t212_holdings_value, 2),
        "t212_cash_value": round(t212_cash_value, 2),
        "t212_total": round(t212_total, 2),
        "t212_last_sync": trading212_settings["last_sync_at"] if "last_sync_at" in trading212_settings.keys() else None,
    }


@app.route("/")
def dashboard():
    conn = get_db()
    payload = dashboard_payload(conn)
    conn.close()
    return render_template("dashboard.html", **payload)











@app.route("/performance")
def performance():
    conn = get_db()
    charts = performance_chart_series(conn)
    conn.close()
    return render_template("performance.html", charts=charts)


@app.route("/pension")
def pension_dashboard():
    conn = get_db()
    rows, summary = performance_rows(conn, pension_only=True, sync_bullion_fn=sync_bullion_account)
    monthly = monthly_performance(conn, pension_only=True)
    pension_accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND COALESCE(is_archived, 0) = 0 AND COALESCE(term_type, '') != 'Ignore' AND account_type = 'Pension' ORDER BY name").fetchall()
    snapshots = conn.execute(
        """
        SELECT s.snapshot_date, SUM(s.value) AS total
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        WHERE a.account_type = 'Pension'
          AND COALESCE(a.term_type, '') != 'Ignore'
        GROUP BY s.snapshot_date
        ORDER BY s.snapshot_date
        """
    ).fetchall()
    recent = conn.execute(
        """
        SELECT t.*, a.name AS account_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.account_type = 'Pension'
          AND COALESCE(a.term_type, '') != 'Ignore'
        ORDER BY t.created_at DESC
        LIMIT 8
        """
    ).fetchall()
    conn.close()
    return render_template(
        "pension.html",
        rows=rows,
        summary=summary,
        pension_accounts=pension_accounts,
        recent_transactions=recent,
        labels=json.dumps([s["snapshot_date"] for s in snapshots]),
        pension_data=json.dumps([round(s["total"], 2) for s in snapshots]),
        monthly=monthly,
        monthly_labels=json.dumps([m["month"] for m in monthly]),
        monthly_contributions=json.dumps([round(m["contributions"], 2) for m in monthly]),
        monthly_value_changes=json.dumps([round(m["value_changes"], 2) for m in monthly]),
    )











@app.route("/bullion")
def bullion():
    conn = get_db()
    items, total_value, total_cost, prices = bullion_rows_with_values(conn)
    sync_bullion_account(conn)
    conn.close()
    return render_template(
        "bullion.html",
        items=items,
        total_value=total_value,
        total_cost=total_cost,
        total_profit=round(total_value - total_cost, 2),
        gold_price=prices["Gold"],
        silver_price=prices["Silver"],
        gold_source=prices["gold_source"],
        silver_source=prices["silver_source"],
    )


@app.route("/bullion/add", methods=["POST"])
def add_bullion():
    name = request.form["name"].strip()
    metal = request.form["metal"]
    weight_grams = float(request.form["weight_grams"])
    purity = float(request.form["purity"])
    quantity = int(request.form["quantity"])
    purchase_price_raw = request.form.get("purchase_price", "").strip()

    conn = get_db()
    prices = get_metal_prices(conn)
    pure_grams = weight_grams * purity * quantity

    # Purchase price is optional. If left blank, use current spot/manual price
    # so you can quickly add holdings when you only know the amount.
    purchase_price = float(purchase_price_raw) if purchase_price_raw else round(pure_grams * prices[metal], 2)

    conn.execute(
        """
        INSERT INTO bullion (name, metal, weight_grams, purity, quantity, purchase_price, acquired_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            metal,
            weight_grams,
            purity,
            quantity,
            purchase_price,
            request.form.get("acquired_date") or date.today().isoformat(),
            request.form.get("notes", "").strip(),
        ),
    )
    conn.commit()
    sync_bullion_account(conn)
    take_snapshot(conn)
    conn.close()
    flash("Bullion item added.")
    return redirect(url_for("bullion"))


@app.route("/bullion/delete/<int:item_id>", methods=["POST"])
def delete_bullion(item_id):
    conn = get_db()
    conn.execute("DELETE FROM bullion WHERE id = ?", (item_id,))
    conn.commit()
    sync_bullion_account(conn)
    take_snapshot(conn)
    conn.close()
    flash("Bullion item deleted.")
    return redirect(url_for("bullion"))





























@app.route("/compound-interest", methods=["GET", "POST"])
def compound_interest():
    conn = get_db()
    trading212_reconcile_auto_account_from_cache(conn, snapshot_fn=take_snapshot)
    accounts = compound_accounts(conn)

    def setting_float(key, default):
        try:
            return float(get_setting(conn, key, default))
        except (TypeError, ValueError):
            return float(default)

    def setting_int(key, default):
        try:
            return int(float(get_setting(conn, key, default)))
        except (TypeError, ValueError):
            return int(default)

    if request.method == "POST":
        annual_rate = float(request.form.get("annual_rate") or 5)
        years = int(float(request.form.get("years") or 5))
        months = int(float(request.form.get("months") or 0))
        annual_increase = float(request.form.get("annual_increase") or 0)

        set_setting(conn, "compound_annual_rate", annual_rate)
        set_setting(conn, "compound_years", years)
        set_setting(conn, "compound_months", months)
        set_setting(conn, "compound_annual_increase", annual_increase)

        for account in accounts:
            key = str(account["id"])
            monthly_value = float(request.form.get(f"monthly_{key}") or 0)
            set_setting(conn, f"compound_monthly_{key}", monthly_value)

        conn.commit()
        flash("Compound interest settings saved.")
    else:
        annual_rate = setting_float("compound_annual_rate", 5)
        years = setting_int("compound_years", 5)
        months = setting_int("compound_months", 0)
        annual_increase = setting_float("compound_annual_increase", 0)

    results = []
    labels = []
    datasets = []
    total_starting = total_contrib = total_future = total_growth = 0.0

    for account in accounts:
        key = str(account["id"])
        default_monthly = 0
        if account["account_type"] == "Lifetime ISA" or account["name"] == "Lifetime ISA":
            default_monthly = 340
        elif account["account_type"] == "Stocks and Shares ISA" or account["name"] == "Stocks and Shares ISA":
            default_monthly = 250

        monthly = setting_float(f"compound_monthly_{key}", default_monthly)
        if request.method == "POST":
            monthly = float(request.form.get(f"monthly_{key}") or 0)

        projection = compound_projection(
            starting_value=account["current_value"],
            annual_rate_pct=annual_rate,
            years=years,
            months=months,
            monthly_contribution=monthly,
            annual_contribution_increase_pct=annual_increase,
        )
        total_starting += projection["starting_value"]
        total_contrib += projection["total_contributed"]
        total_future += projection["future_value"]
        total_growth += projection["growth"]

        point_labels = ["Current"] + [p["year_label"] for p in projection["points"]]
        point_values = [projection["starting_value"]] + [p["value"] for p in projection["points"]]
        if not labels:
            labels = point_labels
        datasets.append({
            "label": account["name"],
            "data": point_values,
        })
        results.append({
            "account": account,
            "monthly": monthly,
            **projection,
        })

    conn.close()
    return render_template(
        "compound_interest.html",
        accounts=accounts,
        results=results,
        annual_rate=annual_rate,
        years=years,
        months=months,
        annual_increase=annual_increase,
        total_starting=round(total_starting, 2),
        total_contributed=round(total_contrib, 2),
        total_future=round(total_future, 2),
        total_growth=round(total_growth, 2),
        chart_labels=json.dumps(labels),
        chart_datasets=json.dumps(datasets),
    )












@app.route("/snapshot", methods=["POST"])
def snapshot():
    conn = get_db()
    sync_bullion_account(conn)
    take_snapshot(conn)
    conn.close()
    flash("Snapshot saved for today.")
    return redirect(url_for("dashboard"))


@app.route("/export/transactions.csv")
def export_transactions():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT t.created_at, a.name AS account_name, a.account_type, t.transaction_type, t.amount, t.note
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        ORDER BY t.created_at DESC
        """
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["created_at", "account_name", "account_type", "transaction_type", "amount", "note"])
    for row in rows:
        writer.writerow([row["created_at"], row["account_name"], row["account_type"], row["transaction_type"], row["amount"], row["note"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


# Run schema creation/migrations at application startup, including Gunicorn imports.
# Hot paths should read from the already-migrated schema rather than checking
# PRAGMA table_info() or committing schema fixes during normal page loads.
init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
