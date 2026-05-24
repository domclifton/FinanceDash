"""Database connection, settings helpers, and schema migrations for InvestHome.

This module owns SQLite connection setup and init-time schema work. It avoids
Flask route/template concerns so future route blueprint extraction can import the
database layer without circular dependencies.
"""

import sqlite3

from config import (
    ACCOUNT_TYPES,
    DB_NAME,
    TRADING212_AUTO_ACCOUNT_NAME,
)


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




def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(sync_bullion_fn=None, take_snapshot_fn=None):
    """Create/migrate the SQLite schema and seed default records.

    Optional post-init callbacks keep live-price syncing and snapshot creation
    caller-controlled so this database layer does not import app/service logic.
    """
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
    if "include_in_net_worth" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN include_in_net_worth INTEGER NOT NULL DEFAULT 1")
    if "is_archived" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    if "archived_at" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN archived_at TEXT")
    if "source_provider" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN source_provider TEXT")
    if "is_auto_managed" not in account_columns:
        cur.execute("ALTER TABLE accounts ADD COLUMN is_auto_managed INTEGER NOT NULL DEFAULT 0")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
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
            FOREIGN KEY(account_id) REFERENCES accounts(id),
            UNIQUE(account_id, snapshot_date)
        )
        """
    )

    # Performance indexes for dashboard/performance chart queries.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(transaction_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account_type_date ON transactions(account_id, transaction_type, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account_type_created_day ON transactions(account_id, transaction_type, date(created_at))")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_account_date ON snapshots(account_id, snapshot_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_account_snapshot_day ON snapshots(account_id, date(snapshot_date))")

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

    couple_columns = [row["name"] for row in cur.execute("PRAGMA table_info(couple_budget_settings)").fetchall()]
    for column_name, column_def in {
        "person_one_name": "TEXT NOT NULL DEFAULT 'Person 1'",
        "person_one_income": "REAL NOT NULL DEFAULT 0",
        "person_two_name": "TEXT NOT NULL DEFAULT 'Person 2'",
        "person_two_income": "REAL NOT NULL DEFAULT 0",
    }.items():
        if column_name not in couple_columns:
            cur.execute(f"ALTER TABLE couple_budget_settings ADD COLUMN {column_name} {column_def}")
    couple_columns = [row["name"] for row in cur.execute("PRAGMA table_info(couple_budget_settings)").fetchall()]
    if "person1_income" in couple_columns:
        cur.execute("UPDATE couple_budget_settings SET person_one_income = COALESCE(person_one_income, person1_income)")
    if "person2_income" in couple_columns:
        cur.execute("UPDATE couple_budget_settings SET person_two_income = COALESCE(person_two_income, person2_income)")

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
    property_columns = [row["name"] for row in cur.execute("PRAGMA table_info(property_settings)").fetchall()]
    if "include_in_net_worth" not in property_columns:
        cur.execute("ALTER TABLE property_settings ADD COLUMN include_in_net_worth INTEGER NOT NULL DEFAULT 1")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            debt_type TEXT NOT NULL DEFAULT 'Other',
            current_balance REAL NOT NULL DEFAULT 0,
            apr REAL NOT NULL DEFAULT 0,
            minimum_payment REAL NOT NULL DEFAULT 0,
            planned_payment REAL NOT NULL DEFAULT 0,
            due_day INTEGER,
            include_in_net_worth INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'Active',
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    debt_columns = [row["name"] for row in cur.execute("PRAGMA table_info(debts)").fetchall()]
    for column_name, column_def in {
        "apr": "REAL NOT NULL DEFAULT 0",
        "minimum_payment": "REAL NOT NULL DEFAULT 0",
        "planned_payment": "REAL NOT NULL DEFAULT 0",
        "due_day": "INTEGER",
        "include_in_net_worth": "INTEGER NOT NULL DEFAULT 1",
        "status": "TEXT NOT NULL DEFAULT 'Active'",
        "note": "TEXT",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }.items():
        if column_name not in debt_columns:
            cur.execute(f"ALTER TABLE debts ADD COLUMN {column_name} {column_def}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trading212_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            environment TEXT NOT NULL DEFAULT 'demo',
            target_account_name TEXT NOT NULL DEFAULT 'Trading 212 ISA (Auto)',
            auto_update_account INTEGER NOT NULL DEFAULT 1,
            last_sync_at TIMESTAMP,
            cash_value REAL NOT NULL DEFAULT 0,
            holdings_value REAL NOT NULL DEFAULT 0,
            portfolio_total REAL NOT NULL DEFAULT 0,
            rate_limit_reset_at TEXT,
            api_key TEXT,
            api_secret TEXT,
            credentials_updated_at TIMESTAMP
        )
    """)

    trading212_columns = [row["name"] for row in cur.execute("PRAGMA table_info(trading212_settings)").fetchall()]
    for column_name, column_def in {
        "cash_value": "REAL NOT NULL DEFAULT 0",
        "holdings_value": "REAL NOT NULL DEFAULT 0",
        "portfolio_total": "REAL NOT NULL DEFAULT 0",
        "rate_limit_reset_at": "TEXT",
        "api_key": "TEXT",
        "api_secret": "TEXT",
        "credentials_updated_at": "TIMESTAMP",
    }.items():
        if column_name not in trading212_columns:
            cur.execute(f"ALTER TABLE trading212_settings ADD COLUMN {column_name} {column_def}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trading212_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            name TEXT,
            quantity REAL NOT NULL DEFAULT 0,
            average_price REAL NOT NULL DEFAULT 0,
            current_price REAL NOT NULL DEFAULT 0,
            average_price_raw REAL NOT NULL DEFAULT 0,
            current_price_raw REAL NOT NULL DEFAULT 0,
            price_currency TEXT DEFAULT 'GBP',
            current_value REAL NOT NULL DEFAULT 0,
            pnl REAL NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'GBP',
            raw_json TEXT,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    trading212_holdings_columns = [row["name"] for row in cur.execute("PRAGMA table_info(trading212_holdings)").fetchall()]
    for column_name, column_def in {
        "average_price_raw": "REAL NOT NULL DEFAULT 0",
        "current_price_raw": "REAL NOT NULL DEFAULT 0",
        "price_currency": "TEXT DEFAULT 'GBP'",
        "name": "TEXT",
    }.items():
        if column_name not in trading212_holdings_columns:
            cur.execute(f"ALTER TABLE trading212_holdings ADD COLUMN {column_name} {column_def}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trading212_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO trading212_settings
        (id, environment, target_account_name, auto_update_account)
        VALUES (1, 'demo', 'Trading 212 ISA (Auto)', 1)
    """)
    cur.execute(
        """
        UPDATE trading212_settings
        SET target_account_name = ?
        WHERE id = 1
          AND (target_account_name IS NULL OR target_account_name = '' OR target_account_name = 'Stocks and Shares ISA')
        """,
        (TRADING212_AUTO_ACCOUNT_NAME,),
    )

    defaults = {
        "manual_gold_gbp_per_g": "60.00",
        "manual_silver_gbp_per_g": "0.75",
        "use_live_prices": "1",
        "goldapi_refresh_mode": "daily",
        "goldapi_cached_gold_gbp_per_g": "",
        "goldapi_cached_silver_gbp_per_g": "",
        "goldapi_last_sync_at": "",
        "goldapi_last_status": "Not synced",
        "goldapi_last_message": "No GoldAPI sync has run yet.",
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

    # One-time migration only: keep the dropdown type table in sync with any
    # categories already present in older/imported databases. This used to happen
    # inside get_account_types(), which made account dropdown rendering commit
    # writes during normal GET requests.
    cur.execute("INSERT OR IGNORE INTO account_types (name) SELECT DISTINCT account_type FROM accounts WHERE account_type IS NOT NULL AND TRIM(account_type) != ''")

    conn.commit()
    if sync_bullion_fn:
        sync_bullion_fn(conn)
    if take_snapshot_fn:
        take_snapshot_fn(conn)
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
    """Return selectable account categories without mutating the database.

    Account type migrations and default inserts are handled in init_db(), so GET
    requests that render account dropdowns cannot silently write/commit changes.
    """
    rows = conn.execute("SELECT name FROM account_types ORDER BY name").fetchall()
    return [row["name"] for row in rows]


