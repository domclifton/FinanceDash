import csv
import io
import json
import os
import sqlite3
from datetime import date, datetime

import requests
from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, url_for

load_dotenv()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(APP_DIR, "finance.db")
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "").strip()
APP_VERSION = "1.20.1"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-change-me")

ACCOUNT_TYPES = [
    "Emergency Fund",
    "Cash ISA",
    "Stocks and Shares ISA",
    "Lifetime ISA",
    "Pension",
    "Premium Bonds",
    "Physical Bullion",
]

TERM_TYPES = ["Emergency", "Liquid", "Short Term", "Mid Term", "Long Term"]


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


def default_term_for_account(account_type):
    mapping = {
        "Emergency Fund": "Emergency",
        "Cash ISA": "Liquid",
        "Premium Bonds": "Liquid",
        "Stocks and Shares ISA": "Long Term",
        "Lifetime ISA": "Long Term",
        "Pension": "Long Term",
        "Physical Bullion": "Mid Term",
    }
    return mapping.get(account_type, "Mid Term")


def is_lifetime_isa(account):
    """Return True for Lifetime ISA accounts by name or category.

    LISA government bonus handling is intentionally applied only when
    adding new money to the account. The bonus is treated as growth/value
    change, not as user contribution.
    """
    name = str(account["name"] or "").lower()
    account_type = str(account["account_type"] or "").lower()
    return "lifetime isa" in name or "lisa" == name.strip() or "lifetime isa" in account_type


def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            term_type TEXT NOT NULL DEFAULT 'Mid Term',
            current_value REAL NOT NULL DEFAULT 0,
            include_in_net_worth INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Lightweight migration for existing databases from earlier versions.
    account_columns = [row["name"] for row in cur.execute("PRAGMA table_info(accounts)").fetchall()]
    if "term_type" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN term_type TEXT NOT NULL DEFAULT 'Mid Term'")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            value REAL NOT NULL,
            snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, snapshot_date)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bullion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            metal TEXT NOT NULL CHECK(metal IN ('Gold', 'Silver')),
            weight_grams REAL NOT NULL,
            purity REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            purchase_price REAL NOT NULL,
            acquired_date DATE DEFAULT CURRENT_DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS account_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS budget_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            income REAL NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS budget_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS couple_budget_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            person_one_name TEXT NOT NULL DEFAULT 'Person 1',
            person_one_income REAL NOT NULL DEFAULT 0,
            person_two_name TEXT NOT NULL DEFAULT 'Person 2',
            person_two_income REAL NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS couple_budget_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream TEXT NOT NULL DEFAULT 'Joint',
            name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute("INSERT OR IGNORE INTO budget_settings (id, income) VALUES (1, 0)")
    cur.execute("""
        INSERT OR IGNORE INTO couple_budget_settings
        (id, person_one_name, person_one_income, person_two_name, person_two_income)
        VALUES (1, 'Person 1', 0, 'Person 2', 0)
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS property_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        home_value REAL NOT NULL DEFAULT 0,
        mortgage_left REAL NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("INSERT OR IGNORE INTO property_settings (id, home_value, mortgage_left) VALUES (1, 0, 0)")

    defaults = {
        "manual_gold_gbp_per_g": "60.00",
        "manual_silver_gbp_per_g": "0.75",
        "use_live_prices": "1",
    }
    for key, value in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    for account_type in ACCOUNT_TYPES:
        cur.execute("INSERT OR IGNORE INTO account_types (name) VALUES (?)", (account_type,))
        name = account_type
        cur.execute(
            """
            INSERT INTO accounts (name, account_type, term_type, current_value)
            SELECT ?, ?, ?, 0
            WHERE NOT EXISTS (
                SELECT 1 FROM accounts WHERE name = ? AND account_type = ?
            )
            """,
            (name, account_type, default_term_for_account(account_type), name, account_type),
        )

    conn.commit()
    sync_bullion_account(conn)
    take_snapshot(conn)
    conn.close()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_account_types(conn):
    rows = conn.execute("SELECT name FROM account_types ORDER BY name").fetchall()
    existing = [row["name"] for row in rows]

    # If upgrading from an older database, pull any account_type values already used
    # and add them to the selectable type list.
    used = conn.execute("SELECT DISTINCT account_type FROM accounts ORDER BY account_type").fetchall()
    for row in used:
        if row["account_type"] not in existing:
            conn.execute("INSERT OR IGNORE INTO account_types (name) VALUES (?)", (row["account_type"],))
            existing.append(row["account_type"])
    conn.commit()
    return sorted(existing)


def fetch_goldapi_price_per_gram(symbol):
    if not GOLDAPI_KEY:
        return None

    url = f"https://www.goldapi.io/api/{symbol}/GBP"
    headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()
        price_per_ounce = float(data["price"])
        return round(price_per_ounce / 31.1035, 4)
    except Exception as exc:
        print(f"GoldAPI fetch failed for {symbol}: {exc}")
        return None


def get_metal_prices(conn):
    manual_gold = float(get_setting(conn, "manual_gold_gbp_per_g", "60"))
    manual_silver = float(get_setting(conn, "manual_silver_gbp_per_g", "0.75"))
    use_live = get_setting(conn, "use_live_prices", "1") == "1"

    gold_live = fetch_goldapi_price_per_gram("XAU") if use_live else None
    silver_live = fetch_goldapi_price_per_gram("XAG") if use_live else None

    return {
        "Gold": gold_live if gold_live else manual_gold,
        "Silver": silver_live if silver_live else manual_silver,
        "gold_source": "Live" if gold_live else "Manual fallback",
        "silver_source": "Live" if silver_live else "Manual fallback",
    }


def bullion_rows_with_values(conn):
    prices = get_metal_prices(conn)
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


def sync_bullion_account(conn):
    items, total_value, _total_cost, _prices = bullion_rows_with_values(conn)
    conn.execute(
        "UPDATE accounts SET current_value = ? WHERE account_type = 'Physical Bullion'",
        (total_value,),
    )
    conn.commit()
    return total_value


def take_snapshot(conn):
    today = date.today().isoformat()
    accounts = conn.execute("SELECT id, current_value FROM accounts").fetchall()
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



def performance_rows(conn, pension_only=False):
    sync_bullion_account(conn)
    if pension_only:
        accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND account_type = 'Pension' ORDER BY account_type, name").fetchall()
    else:
        accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND account_type != 'Pension' ORDER BY account_type, name").fetchall()
    rows = []
    total_current = total_contributions = total_growth = 0.0

    for account in accounts:
        tx = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type IN ('add', 'remove') THEN amount ELSE 0 END), 0) AS net_contributions,
                COALESCE(SUM(CASE WHEN transaction_type = 'value_update' THEN amount ELSE 0 END), 0) AS valuation_changes
            FROM transactions
            WHERE account_id = ?
            """,
            (account["id"],),
        ).fetchone()

        current = float(account["current_value"] or 0)
        contributions = float(tx["net_contributions"] or 0)

        # Physical Bullion is itemised; use purchase cost as its contribution baseline.
        if account["account_type"] == "Physical Bullion":
            bullion_cost = conn.execute("SELECT COALESCE(SUM(purchase_price), 0) AS cost FROM bullion").fetchone()["cost"]
            contributions = float(bullion_cost or 0)

        growth = current - contributions
        growth_pct = (growth / contributions * 100) if contributions else 0
        total_current += current
        total_contributions += contributions
        total_growth += growth

        rows.append({
            "id": account["id"],
            "name": account["name"],
            "account_type": account["account_type"],
            "current_value": round(current, 2),
            "net_contributions": round(contributions, 2),
            "growth": round(growth, 2),
            "growth_pct": round(growth_pct, 2),
            "can_update_value": account["account_type"] != "Physical Bullion",
        })

    total_growth_pct = (total_growth / total_contributions * 100) if total_contributions else 0
    return rows, {
        "total_current": round(total_current, 2),
        "total_contributions": round(total_contributions, 2),
        "total_growth": round(total_growth, 2),
        "total_growth_pct": round(total_growth_pct, 2),
    }


def monthly_performance(conn, pension_only=False):
    if pension_only:
        filter_sql = "AND a.account_type = 'Pension'"
    else:
        filter_sql = "AND a.account_type != 'Pension'"
    rows = conn.execute(
        f"""
        SELECT
            substr(t.created_at, 1, 7) AS month,
            COALESCE(SUM(CASE WHEN t.transaction_type IN ('add', 'remove') THEN t.amount ELSE 0 END), 0) AS contributions,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'value_update' THEN t.amount ELSE 0 END), 0) AS value_changes
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE 1 = 1 {filter_sql}
        GROUP BY substr(t.created_at, 1, 7)
        ORDER BY month
        """
    ).fetchall()
    return rows



def _svg_chart_payload(labels, contribution_points, value_points):
    """Create server-rendered SVG line chart data so performance charts work without Chart.js."""
    width = 1000
    height = 300
    left = 70
    right = 25
    top = 24
    bottom = 48
    plot_w = width - left - right
    plot_h = height - top - bottom

    all_values = [float(v or 0) for v in contribution_points + value_points]
    max_y = max(all_values + [1])
    max_y = max_y * 1.10 if max_y > 0 else 1
    min_y = 0

    def x_pos(i):
        if len(labels) <= 1:
            return left + plot_w
        return left + (i / (len(labels) - 1)) * plot_w

    def y_pos(v):
        return top + ((max_y - float(v or 0)) / (max_y - min_y)) * plot_h

    contribution_xy = [(x_pos(i), y_pos(v)) for i, v in enumerate(contribution_points)]
    value_xy = [(x_pos(i), y_pos(v)) for i, v in enumerate(value_points)]

    contribution_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in contribution_xy)
    value_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in value_xy)
    fill_polygon = " ".join(f"{x:.1f},{y:.1f}" for x, y in value_xy + list(reversed(contribution_xy)))

    ticks = []
    for i in range(5):
        val = max_y * i / 4
        y = y_pos(val)
        ticks.append({"y": round(y, 1), "label": f"£{val:,.0f}"})

    x_ticks = []
    if labels:
        if len(labels) <= 8:
            indexes = list(range(len(labels)))
        else:
            indexes = sorted(set([0, len(labels)//4, len(labels)//2, (len(labels)*3)//4, len(labels)-1]))
        for i in indexes:
            x_ticks.append({"x": round(x_pos(i), 1), "label": labels[i]})

    return {
        "width": width,
        "height": height,
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "plot_bottom": height - bottom,
        "plot_right": width - right,
        "contribution_polyline": contribution_polyline,
        "value_polyline": value_polyline,
        "fill_polygon": fill_polygon,
        "ticks": ticks,
        "x_ticks": x_ticks,
        "contribution_points": [{"x": round(x, 1), "y": round(y, 1)} for x, y in contribution_xy],
        "value_points": [{"x": round(x, 1), "y": round(y, 1)} for x, y in value_xy],
    }


def performance_chart_series(conn):
    """Build individual over-time charts for key long-term accounts.

    Blue shows cumulative contributions/money paid in.
    Green shows current value. When green is above blue, the account is in profit.
    """
    targets = [
        {"title": "Stocks and Shares ISA Over Time", "match": "Stocks and Shares ISA"},
        {"title": "Lifetime ISA Over Time", "match": "Lifetime ISA"},
        {"title": "Pension Over Time", "match": "Pension"},
    ]
    charts = []

    for target in targets:
        account = conn.execute(
            """
            SELECT * FROM accounts
            WHERE name = ? OR account_type = ?
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (target["match"], target["match"], target["match"]),
        ).fetchone()

        if not account:
            labels = []
            contribution_points = []
            value_points = []
            current_value = current_contributions = current_growth = current_growth_pct = 0
            account_name = target["match"]
        else:
            snapshots = conn.execute(
                """
                SELECT snapshot_date, value
                FROM snapshots
                WHERE account_id = ?
                ORDER BY snapshot_date
                """,
                (account["id"],),
            ).fetchall()

            if not snapshots:
                today = date.today().isoformat()
                snapshots = [{"snapshot_date": today, "value": account["current_value"]}]

            labels = []
            contribution_points = []
            value_points = []

            for snap in snapshots:
                snap_date = snap["snapshot_date"]
                contributions_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) AS total
                    FROM transactions
                    WHERE account_id = ?
                      AND transaction_type IN ('add', 'remove')
                      AND date(created_at) <= date(?)
                    """,
                    (account["id"], snap_date),
                ).fetchone()
                contributions = float(contributions_row["total"] or 0)
                value = float(snap["value"] or 0)

                labels.append(snap_date)
                contribution_points.append(round(contributions, 2))
                value_points.append(round(value, 2))

            current_contributions = contribution_points[-1] if contribution_points else 0
            current_value = value_points[-1] if value_points else round(float(account["current_value"] or 0), 2)
            current_growth = round(current_value - current_contributions, 2)
            current_growth_pct = round((current_growth / current_contributions * 100), 2) if current_contributions else 0
            account_name = account["name"]

        charts.append({
            "title": target["title"],
            "account_name": account_name,
            "current_value": current_value,
            "current_contributions": current_contributions,
            "current_growth": current_growth,
            "current_growth_pct": current_growth_pct,
            "svg": _svg_chart_payload(labels, contribution_points, value_points),
        })

    return charts


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
    wanted = ["Pension", "Lifetime ISA", "Stocks and Shares ISA"]
    rows = conn.execute(
        """
        SELECT * FROM accounts
        WHERE account_type IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
           OR name IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
        ORDER BY CASE
            WHEN account_type = 'Pension' OR name = 'Pension' THEN 1
            WHEN account_type = 'Lifetime ISA' OR name = 'Lifetime ISA' THEN 2
            WHEN account_type = 'Stocks and Shares ISA' OR name = 'Stocks and Shares ISA' THEN 3
            ELSE 4
        END, name
        """
    ).fetchall()

    # Make sure useful rows exist even on a fresh database.
    existing_names = {row["name"] for row in rows}
    for name in wanted:
        if name not in existing_names:
            conn.execute("INSERT OR IGNORE INTO account_types (name) VALUES (?)", (name,))
            conn.execute(
                """
                INSERT INTO accounts (name, account_type, term_type, current_value)
                VALUES (?, ?, ?, 0)
                """,
                (name, name, default_term_for_account(name)),
            )
    conn.commit()

    return conn.execute(
        """
        SELECT * FROM accounts
        WHERE account_type IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
           OR name IN ('Pension', 'Lifetime ISA', 'Stocks and Shares ISA')
        ORDER BY CASE
            WHEN account_type = 'Pension' OR name = 'Pension' THEN 1
            WHEN account_type = 'Lifetime ISA' OR name = 'Lifetime ISA' THEN 2
            WHEN account_type = 'Stocks and Shares ISA' OR name = 'Stocks and Shares ISA' THEN 3
            ELSE 4
        END, name
        """
    ).fetchall()

def dashboard_payload(conn):
    sync_bullion_account(conn)
    accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND account_type != 'Pension' ORDER BY account_type").fetchall()
    total = sum(a["current_value"] for a in accounts)

    # Main-dashboard buckets are driven by the editable term_type dropdown on Accounts.
    # Pension stays separate because it is inaccessible until retirement.
    emergency = sum(a["current_value"] for a in accounts if a["term_type"] == "Emergency")
    liquid = sum(a["current_value"] for a in accounts if a["term_type"] == "Liquid")
    short_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Short Term")
    mid_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Mid Term")
    long_term = sum(a["current_value"] for a in accounts if a["term_type"] == "Long Term")
    pension = conn.execute("SELECT COALESCE(SUM(current_value), 0) AS total FROM accounts WHERE include_in_net_worth = 1 AND account_type = 'Pension'").fetchone()["total"]

    property_row = conn.execute("SELECT home_value, mortgage_left FROM property_settings WHERE id = 1").fetchone()
    property_home_value = float(property_row["home_value"] or 0) if property_row else 0.0
    property_mortgage_left = float(property_row["mortgage_left"] or 0) if property_row else 0.0
    property_equity = property_home_value - property_mortgage_left

    total_all_assets = total + float(pension or 0) + property_equity

    category = {"Emergency": emergency, "Liquid": liquid, "Short Term": short_term, "Mid Term": mid_term, "Long Term": long_term}
    category = {k: v for k, v in category.items() if v}

    snapshots = conn.execute(
        """
        SELECT s.snapshot_date, SUM(s.value) AS total
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        WHERE a.account_type != 'Pension'
        GROUP BY s.snapshot_date
        ORDER BY s.snapshot_date
        """
    ).fetchall()

    recent = conn.execute(
        """
        SELECT t.*, a.name AS account_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.account_type != 'Pension'
        ORDER BY t.created_at DESC
        LIMIT 8
        """
    ).fetchall()

    perf_rows, perf_summary = performance_rows(conn, pension_only=False)

    return {
        "accounts": accounts,
        "total": round(total, 2),
        "emergency": round(emergency, 2),
        "liquid": round(liquid, 2),
        "short_term": round(short_term, 2),
        "mid_term": round(mid_term, 2),
        "long_term": round(long_term, 2),
        "pension": round(pension, 2),
        "property_home_value": round(property_home_value, 2),
        "property_mortgage_left": round(property_mortgage_left, 2),
        "property_equity": round(property_equity, 2),
        "total_all_assets": round(total_all_assets, 2),
        "category_labels": json.dumps(list(category.keys())),
        "category_data": json.dumps([round(v, 2) for v in category.values()]),
        "labels": json.dumps([s["snapshot_date"] for s in snapshots]),
        "networth_data": json.dumps([round(s["total"], 2) for s in snapshots]),
        "recent_transactions": recent,
        "performance_rows": perf_rows,
        "total_contributions": perf_summary["total_contributions"],
        "total_growth": perf_summary["total_growth"],
        "total_growth_pct": perf_summary["total_growth_pct"],
    }


@app.route("/")
def dashboard():
    conn = get_db()
    payload = dashboard_payload(conn)
    conn.close()
    return render_template("dashboard.html", **payload)


@app.route("/accounts")
def accounts():
    conn = get_db()
    sync_bullion_account(conn)
    accounts = conn.execute("SELECT * FROM accounts ORDER BY account_type, name").fetchall()
    account_types = get_account_types(conn)
    conn.close()
    return render_template("accounts.html", accounts=accounts, account_types=account_types, term_types=TERM_TYPES)


@app.route("/accounts/add", methods=["POST"])
def add_account():
    name = request.form["name"].strip()
    account_type = request.form.get("new_account_type", "").strip() or request.form["account_type"].strip()
    term_type = request.form.get("term_type", default_term_for_account(account_type)).strip()
    if term_type not in TERM_TYPES:
        term_type = default_term_for_account(account_type)
    starting_value = float(request.form.get("starting_value") or 0)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO account_types (name) VALUES (?)", (account_type,))
    cur.execute(
        "INSERT INTO accounts (name, account_type, term_type, current_value) VALUES (?, ?, ?, ?)",
        (name, account_type, term_type, starting_value),
    )
    account_id = cur.lastrowid
    if starting_value:
        cur.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'add', ?, 'Starting balance')",
            (account_id, starting_value),
        )
    conn.commit()
    take_snapshot(conn)
    conn.close()
    flash("Account added.")
    return redirect(url_for("accounts"))


@app.route("/transaction/add", methods=["POST"])
def add_transaction():
    account_id = int(request.form["account_id"])
    transaction_type = request.form["transaction_type"]
    amount = abs(float(request.form["amount"]))
    note = request.form.get("note", "").strip()
    signed_amount = -amount if transaction_type == "remove" else amount

    conn = get_db()
    account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        conn.close()
        flash("Account not found.")
        return redirect(url_for("accounts"))
    if account["account_type"] == "Physical Bullion":
        conn.close()
        flash("Physical Bullion is calculated from bullion holdings. Add/remove items from the Bullion page.")
        return redirect(url_for("bullion"))

    bonus_amount = 0.0
    if transaction_type == "add" and is_lifetime_isa(account):
        bonus_amount = round(amount * 0.25, 2)

    conn.execute(
        "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, ?, ?, ?)",
        (account_id, transaction_type, signed_amount, note),
    )

    if bonus_amount:
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'value_update', ?, ?)",
            (account_id, bonus_amount, "Lifetime ISA 25% government bonus treated as growth"),
        )

    total_account_change = signed_amount + bonus_amount
    conn.execute("UPDATE accounts SET current_value = current_value + ? WHERE id = ?", (total_account_change, account_id))
    conn.commit()
    take_snapshot(conn)
    conn.close()

    if bonus_amount:
        flash(f"Transaction saved. Lifetime ISA bonus of {format_money(bonus_amount)} added as growth.")
    else:
        flash("Transaction saved.")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/transactions")
def transactions():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT t.*, a.name AS account_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        ORDER BY t.created_at DESC
        LIMIT 200
        """
    ).fetchall()
    accounts = conn.execute("SELECT * FROM accounts WHERE account_type != 'Physical Bullion' ORDER BY name").fetchall()
    conn.close()
    return render_template("transactions.html", transactions=rows, accounts=accounts)


@app.route("/performance")
def performance():
    conn = get_db()
    charts = performance_chart_series(conn)
    conn.close()
    return render_template("performance.html", charts=charts)


@app.route("/pension")
def pension_dashboard():
    conn = get_db()
    rows, summary = performance_rows(conn, pension_only=True)
    monthly = monthly_performance(conn, pension_only=True)
    pension_accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND account_type = 'Pension' ORDER BY name").fetchall()
    snapshots = conn.execute(
        """
        SELECT s.snapshot_date, SUM(s.value) AS total
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        WHERE a.account_type = 'Pension'
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


@app.route("/accounts/update-term", methods=["POST"])
def update_account_term():
    account_id = int(request.form["account_id"])
    term_type = request.form.get("term_type", "").strip()

    if term_type not in TERM_TYPES:
        flash("Invalid term type selected.")
        return redirect(url_for("accounts"))

    conn = get_db()
    account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        conn.close()
        flash("Account not found.")
        return redirect(url_for("accounts"))

    conn.execute("UPDATE accounts SET term_type = ? WHERE id = ?", (term_type, account_id))
    conn.commit()
    conn.close()
    flash("Account type updated.")
    return redirect(url_for("accounts"))


@app.route("/accounts/update-value", methods=["POST"])
def update_account_value():
    account_id = int(request.form["account_id"])
    new_value = float(request.form["new_value"])
    note = request.form.get("note", "").strip()

    conn = get_db()
    account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not account:
        conn.close()
        flash("Account not found.")
        return redirect(url_for("accounts"))

    if account["account_type"] == "Physical Bullion":
        conn.close()
        flash("Physical Bullion is calculated from bullion holdings and metal prices.")
        return redirect(url_for("bullion"))

    old_value = float(account["current_value"] or 0)
    delta = round(new_value - old_value, 2)
    if delta == 0:
        conn.close()
        flash("Value unchanged.")
        return redirect(request.referrer or url_for("accounts"))

    clean_note = note or f"Value updated from {format_money(old_value)} to {format_money(new_value)}"
    conn.execute(
        "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'value_update', ?, ?)",
        (account_id, delta, clean_note),
    )
    conn.execute("UPDATE accounts SET current_value = ? WHERE id = ?", (new_value, account_id))
    conn.commit()
    take_snapshot(conn)
    conn.close()
    flash("Asset value updated.")
    return redirect(request.referrer or url_for("accounts"))


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



@app.route("/budget")
def budget():
    return redirect(url_for("budget_solo"))


@app.route("/budget/solo")
def budget_solo():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO budget_settings (id, income) VALUES (1, 0)")
    conn.commit()

    income = cur.execute("SELECT income FROM budget_settings WHERE id = 1").fetchone()["income"]
    items = cur.execute("SELECT * FROM budget_items ORDER BY id").fetchall()
    total_outgoings = sum(float(item["amount"] or 0) for item in items)
    floating_left = float(income or 0) - total_outgoings

    conn.close()
    return render_template(
        "budget_solo.html",
        income=income,
        items=items,
        total_outgoings=total_outgoings,
        floating_left=floating_left,
    )


@app.route("/budget/solo/income", methods=["POST"])
def update_budget_income():
    income = float(request.form.get("income") or 0)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO budget_settings (id, income) VALUES (1, ?)",
        (income,),
    )
    conn.commit()
    conn.close()
    flash("Solo budget income updated.")
    return redirect(url_for("budget_solo"))


@app.route("/budget/solo/add", methods=["POST"])
def add_budget_item():
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    if not name:
        flash("Budget topic name is required.")
        return redirect(url_for("budget_solo"))

    conn = get_db()
    conn.execute("INSERT INTO budget_items (name, amount) VALUES (?, ?)", (name, amount))
    conn.commit()
    conn.close()
    flash("Solo budget item added.")
    return redirect(url_for("budget_solo"))


@app.route("/budget/solo/update/<int:item_id>", methods=["POST"])
def update_budget_item(item_id):
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    conn = get_db()
    conn.execute("UPDATE budget_items SET name = ?, amount = ? WHERE id = ?", (name, amount, item_id))
    conn.commit()
    conn.close()
    flash("Solo budget item updated.")
    return redirect(url_for("budget_solo"))


@app.route("/budget/solo/delete/<int:item_id>", methods=["POST"])
def delete_budget_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM budget_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Solo budget item deleted.")
    return redirect(url_for("budget_solo"))


@app.route("/budget/couple")
def budget_couple():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO couple_budget_settings
        (id, person_one_name, person_one_income, person_two_name, person_two_income)
        VALUES (1, 'Person 1', 0, 'Person 2', 0)
    """)
    conn.commit()

    settings = cur.execute("SELECT * FROM couple_budget_settings WHERE id = 1").fetchone()
    items = cur.execute("SELECT * FROM couple_budget_items ORDER BY stream, id").fetchall()

    person_one_income = float(settings["person_one_income"] or 0)
    person_two_income = float(settings["person_two_income"] or 0)
    combined_income = person_one_income + person_two_income
    total_outgoings = sum(float(item["amount"] or 0) for item in items)
    floating_left = combined_income - total_outgoings

    stream_totals = {"Joint": 0.0, "Person 1": 0.0, "Person 2": 0.0}
    for item in items:
        stream = item["stream"] or "Joint"
        stream_totals[stream] = stream_totals.get(stream, 0.0) + float(item["amount"] or 0)

    conn.close()
    return render_template(
        "budget_couple.html",
        settings=settings,
        items=items,
        person_one_income=person_one_income,
        person_two_income=person_two_income,
        combined_income=combined_income,
        total_outgoings=total_outgoings,
        floating_left=floating_left,
        stream_totals=stream_totals,
    )


@app.route("/budget/couple/income", methods=["POST"])
def update_couple_budget_income():
    person_one_name = request.form.get("person_one_name", "Person 1").strip() or "Person 1"
    person_two_name = request.form.get("person_two_name", "Person 2").strip() or "Person 2"
    person_one_income = float(request.form.get("person_one_income") or 0)
    person_two_income = float(request.form.get("person_two_income") or 0)

    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO couple_budget_settings
        (id, person_one_name, person_one_income, person_two_name, person_two_income)
        VALUES (1, ?, ?, ?, ?)
    """, (person_one_name, person_one_income, person_two_name, person_two_income))
    conn.commit()
    conn.close()
    flash("Couple budget income updated.")
    return redirect(url_for("budget_couple"))


@app.route("/budget/couple/add", methods=["POST"])
def add_couple_budget_item():
    stream = request.form.get("stream", "Joint").strip() or "Joint"
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    if not name:
        flash("Budget topic name is required.")
        return redirect(url_for("budget_couple"))

    conn = get_db()
    conn.execute("INSERT INTO couple_budget_items (stream, name, amount) VALUES (?, ?, ?)", (stream, name, amount))
    conn.commit()
    conn.close()
    flash("Couple budget item added.")
    return redirect(url_for("budget_couple"))


@app.route("/budget/couple/update/<int:item_id>", methods=["POST"])
def update_couple_budget_item(item_id):
    stream = request.form.get("stream", "Joint").strip() or "Joint"
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    conn = get_db()
    conn.execute("UPDATE couple_budget_items SET stream = ?, name = ?, amount = ? WHERE id = ?", (stream, name, amount, item_id))
    conn.commit()
    conn.close()
    flash("Couple budget item updated.")
    return redirect(url_for("budget_couple"))


@app.route("/budget/couple/delete/<int:item_id>", methods=["POST"])
def delete_couple_budget_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM couple_budget_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Couple budget item deleted.")
    return redirect(url_for("budget_couple"))



@app.route("/property", methods=["GET", "POST"])
def property_page():
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO property_settings (id, home_value, mortgage_left) VALUES (1, 0, 0)")
    conn.commit()

    if request.method == "POST":
        home_value = float(request.form.get("home_value") or 0)
        mortgage_left = float(request.form.get("mortgage_left") or 0)
        conn.execute(
            """
            INSERT OR REPLACE INTO property_settings (id, home_value, mortgage_left, updated_at)
            VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            """,
            (home_value, mortgage_left),
        )
        conn.commit()
        flash("Property values updated.")

    prop = conn.execute("SELECT * FROM property_settings WHERE id = 1").fetchone()
    home_value = float(prop["home_value"] or 0)
    mortgage_left = float(prop["mortgage_left"] or 0)
    equity = home_value - mortgage_left
    loan_to_value = (mortgage_left / home_value * 100) if home_value else 0
    equity_pct = (equity / home_value * 100) if home_value else 0
    conn.close()

    return render_template(
        "property.html",
        home_value=round(home_value, 2),
        mortgage_left=round(mortgage_left, 2),
        equity=round(equity, 2),
        loan_to_value=round(loan_to_value, 2),
        equity_pct=round(equity_pct, 2),
    )


@app.route("/compound-interest", methods=["GET", "POST"])
def compound_interest():
    conn = get_db()
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


@app.route("/settings", methods=["GET", "POST"])
def settings():
    conn = get_db()
    if request.method == "POST":
        set_setting(conn, "manual_gold_gbp_per_g", request.form["manual_gold_gbp_per_g"])
        set_setting(conn, "manual_silver_gbp_per_g", request.form["manual_silver_gbp_per_g"])
        set_setting(conn, "use_live_prices", "1" if request.form.get("use_live_prices") == "on" else "0")
        conn.commit()
        sync_bullion_account(conn)
        take_snapshot(conn)
        flash("Settings saved.")
        conn.close()
        return redirect(url_for("settings"))

    values = {
        "manual_gold_gbp_per_g": get_setting(conn, "manual_gold_gbp_per_g"),
        "manual_silver_gbp_per_g": get_setting(conn, "manual_silver_gbp_per_g"),
        "use_live_prices": get_setting(conn, "use_live_prices") == "1",
        "has_goldapi_key": bool(GOLDAPI_KEY),
    }
    conn.close()
    return render_template("settings.html", **values)


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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
