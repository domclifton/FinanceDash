"""Trading 212 service helpers for InvestHome.

Extracted during the v3 backend refactor. This module contains only the
Trading 212 API/cache/account-sync logic and keeps route behaviour unchanged.
"""

import base64
import json
import os
from datetime import datetime

import requests

from config import (
    APP_DIR,
    TRADING212_AUTO_ACCOUNT_NAME,
    TRADING212_AUTO_ACCOUNT_TYPE,
    TRADING212_AUTO_TERM_TYPE,
    TRADING212_PROVIDER,
)


def _format_money(value, decimals=2):
    """Small local formatter for transaction/log notes without importing app.py."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    sign = "-" if number < 0 else ""
    return f"{sign}£{abs(number):,.{decimals}f}"


def trading212_base_url(environment):
    """Return Trading 212 API base URL for demo/live."""
    return "https://live.trading212.com/api/v0" if environment == "live" else "https://demo.trading212.com/api/v0"


class Trading212RateLimitError(RuntimeError):
    """Raised when Trading 212 returns HTTP 429 with a reset time."""

    def __init__(self, reset_epoch=None):
        self.reset_epoch = reset_epoch
        self.reset_at = None
        if reset_epoch:
            try:
                self.reset_at = datetime.fromtimestamp(int(reset_epoch)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                self.reset_at = str(reset_epoch)
        message = "Trading 212 rate limit reached"
        if self.reset_at:
            message += f". Try again after {self.reset_at}"
        super().__init__(message)


def is_auto_managed_account(account):
    """Return True when an account value is owned by an external/API provider."""
    if not account:
        return False
    try:
        keys = account.keys()
        source_provider = str(account["source_provider"] or "").strip().lower() if "source_provider" in keys else ""
        is_auto_managed = int(account["is_auto_managed"] or 0) == 1 if "is_auto_managed" in keys else False
    except Exception:
        return False
    return is_auto_managed or bool(source_provider)


def is_trading212_auto_account(account):
    """Return True when an account is the Trading 212 API-managed account row."""
    if not account:
        return False
    try:
        keys = account.keys()
        source_provider = str(account["source_provider"] or "").strip().lower() if "source_provider" in keys else ""
        is_auto_managed = int(account["is_auto_managed"] or 0) == 1 if "is_auto_managed" in keys else False
    except Exception:
        return False
    return source_provider == TRADING212_PROVIDER and is_auto_managed


def trading212_get_or_create_auto_account(conn):
    """Return the Trading 212 API-managed account, converting an old manual row if present.

    This avoids broad category matching such as 'Stocks and Shares ISA', which could
    accidentally update unrelated accounts like Monzo, Vanguard or AJ Bell.
    """
    target = conn.execute(
        """
        SELECT * FROM accounts
        WHERE COALESCE(is_archived, 0) = 0
          AND COALESCE(source_provider, '') = ?
          AND COALESCE(is_auto_managed, 0) = 1
        ORDER BY id
        LIMIT 1
        """,
        (TRADING212_PROVIDER,),
    ).fetchone()

    if not target:
        target = conn.execute(
            """
            SELECT * FROM accounts
            WHERE COALESCE(is_archived, 0) = 0
              AND COALESCE(source_provider, '') = ''
              AND LOWER(REPLACE(name, ' ', '')) IN ('trading212isa', 'trading212')
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

    if not target:
        target = conn.execute(
            """
            SELECT * FROM accounts
            WHERE COALESCE(is_archived, 0) = 0
              AND name = ?
            ORDER BY id
            LIMIT 1
            """,
            (TRADING212_AUTO_ACCOUNT_NAME,),
        ).fetchone()

    if target:
        conn.execute(
            """
            UPDATE accounts
            SET name = ?,
                account_type = ?,
                term_type = CASE
                    WHEN term_type IS NULL OR term_type = '' THEN ?
                    ELSE term_type
                END,
                source_provider = ?,
                is_auto_managed = 1
            WHERE id = ?
            """,
            (
                TRADING212_AUTO_ACCOUNT_NAME,
                TRADING212_AUTO_ACCOUNT_TYPE,
                TRADING212_AUTO_TERM_TYPE,
                TRADING212_PROVIDER,
                target["id"],
            ),
        )
        return conn.execute("SELECT * FROM accounts WHERE id = ?", (target["id"],)).fetchone()

    conn.execute(
        """
        INSERT INTO accounts
        (name, account_type, term_type, current_value, source_provider, is_auto_managed)
        VALUES (?, ?, ?, 0, ?, 1)
        """,
        (
            TRADING212_AUTO_ACCOUNT_NAME,
            TRADING212_AUTO_ACCOUNT_TYPE,
            TRADING212_AUTO_TERM_TYPE,
            TRADING212_PROVIDER,
        ),
    )
    new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (new_id,)).fetchone()


def trading212_archive_duplicate_accounts(conn, keep_account_id):
    """Hide duplicate Trading 212 rows once the provider-managed row exists."""
    conn.execute(
        """
        UPDATE accounts
        SET is_archived = 1,
            archived_at = CURRENT_TIMESTAMP
        WHERE COALESCE(is_archived, 0) = 0
          AND id != ?
          AND (
              COALESCE(source_provider, '') = ?
              OR LOWER(REPLACE(name, ' ', '')) IN ('trading212isa', 'trading212', 'trading212isa(auto)')
          )
        """,
        (keep_account_id, TRADING212_PROVIDER),
    )


def trading212_cached_total(settings):
    """Return the last known Trading 212 total from cached sync settings."""
    if not settings:
        return 0.0
    keys = settings.keys()
    try:
        if "portfolio_total" in keys and settings["portfolio_total"] is not None:
            return round(float(settings["portfolio_total"] or 0), 2)
        cash = float(settings["cash_value"] or 0) if "cash_value" in keys else 0.0
        holdings = float(settings["holdings_value"] or 0) if "holdings_value" in keys else 0.0
        return round(cash + holdings, 2)
    except (TypeError, ValueError):
        return 0.0


def trading212_has_cached_sync(settings):
    """Return True once Trading 212 has produced at least one cached sync.

    v2.8.2 still respected the older auto_update_account toggle. If that toggle
    was off, deleting the manual Trading212 ISA row left no active Account
    Balances row even though the Trading 212 page had a cached value. From
    v2.8.3 the Account Balances row is part of the integration and is recreated
    whenever a cached sync exists.
    """
    if not settings:
        return False
    keys = settings.keys()
    last_sync_at = settings["last_sync_at"] if "last_sync_at" in keys else None
    return bool(last_sync_at)


def trading212_reconcile_auto_account_from_cache(conn, make_snapshot=True, snapshot_fn=None):
    """Mirror the latest cached Trading 212 sync into Account Balances.

    The Trading 212 page, Accounts, Dashboard and Compound Interest pages should
    all read the same Trading 212 value. The auto-managed account is now always
    recreated from cached Trading 212 data, even if an old manual account was
    deleted/archived or the legacy auto-update toggle was switched off.
    """
    settings = trading212_get_settings(conn)
    if not trading212_has_cached_sync(settings):
        return None

    # Keep legacy installs aligned: this integration always manages its own
    # Account Balances row. The column remains for compatibility only.
    if "auto_update_account" in settings.keys() and int(settings["auto_update_account"] or 0) != 1:
        conn.execute("UPDATE trading212_settings SET auto_update_account = 1 WHERE id = 1")

    portfolio_total = trading212_cached_total(settings)
    target = trading212_get_or_create_auto_account(conn)
    old_value = float(target["current_value"] or 0)
    delta = round(portfolio_total - old_value, 2)

    if delta:
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'value_update', ?, ?)",
            (target["id"], delta, f"Trading 212 cached sync reconciled {TRADING212_AUTO_ACCOUNT_NAME} from {_format_money(old_value)} to {_format_money(portfolio_total)}"),
        )

    conn.execute(
        """
        UPDATE accounts
        SET current_value = ?,
            name = ?,
            account_type = ?,
            term_type = CASE
                WHEN term_type IS NULL OR term_type = '' THEN ?
                ELSE term_type
            END,
            source_provider = ?,
            is_auto_managed = 1,
            is_archived = 0,
            archived_at = NULL
        WHERE id = ?
        """,
        (
            portfolio_total,
            TRADING212_AUTO_ACCOUNT_NAME,
            TRADING212_AUTO_ACCOUNT_TYPE,
            TRADING212_AUTO_TERM_TYPE,
            TRADING212_PROVIDER,
            target["id"],
        ),
    )
    trading212_archive_duplicate_accounts(conn, target["id"])

    if make_snapshot and delta and snapshot_fn:
        snapshot_fn(conn)

    conn.commit()
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (target["id"],)).fetchone()


def trading212_get_credentials(conn):
    """Return Trading 212 credentials saved in the app settings database."""
    api_key = ""
    api_secret = ""
    row = trading212_get_settings(conn)
    if row and "api_key" in row.keys():
        api_key = str(row["api_key"] or "").strip()
    if row and "api_secret" in row.keys():
        api_secret = str(row["api_secret"] or "").strip()
    return api_key, api_secret


def trading212_credentials_present(conn):
    api_key, api_secret = trading212_get_credentials(conn)
    return bool(api_key and api_secret)


def trading212_auth_headers(api_key, api_secret):
    """Build the explicit Trading 212 Basic Authorization header.

    Trading 212 expects API key as the Basic Auth username and API secret as
    the Basic Auth password. Building the header here makes that behaviour
    obvious and avoids any ambiguity around requests.get(..., auth=...).
    """
    credentials = f"{api_key}:{api_secret}".encode("utf-8")
    token = base64.b64encode(credentials).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def trading212_api_get(environment, path, conn):
    """Call Trading 212 read-only endpoint using credentials saved in Settings."""
    api_key, api_secret = trading212_get_credentials(conn)
    if not api_key or not api_secret:
        raise RuntimeError("Trading 212 API credentials are missing. Add them in Settings → Trading 212 Connection.")

    url = trading212_base_url(environment) + path
    response = requests.get(url, headers=trading212_auth_headers(api_key, api_secret), timeout=15)

    if response.status_code == 429:
        raise Trading212RateLimitError(response.headers.get("x-ratelimit-reset"))

    response.raise_for_status()
    return response.json()


def _dig(data, path, default=None):
    """Safely read nested dict/list values, e.g. _dig(row, 'instrument.ticker')."""
    cur = data
    for part in path.split('.'):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            cur = None
        if cur is None:
            return default
    return cur


def _first_number(data, keys, default=0.0):
    """Pick first numeric-looking value from a dict, including nested dot paths."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = _dig(data, key) if '.' in key else data.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


def _first_text(data, keys, default=""):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = _dig(data, key) if '.' in key else data.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def normalise_trading212_money(value, currency_code):
    """Convert Trading 212 price values into account-display pounds.

    UK listed instruments can quote prices in GBX, where the numeric value is pence.
    Example: 1,234 GBX should be stored/displayed as £12.34.
    """
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0

    code = str(currency_code or "").upper().strip()
    if code == "GBX":
        return numeric / 100
    return numeric


def _first_money_with_currency(data, amount_keys, currency_keys, default_currency="GBP"):
    """Return raw amount, currency code, and GBP/account-display normalised amount."""
    raw_amount = _first_number(data, amount_keys, 0.0)
    currency_code = _first_text(data, currency_keys, default_currency)
    normalised_amount = normalise_trading212_money(raw_amount, currency_code)
    return raw_amount, currency_code, normalised_amount


def _debug_dump_trading212(summary, positions):
    """Write the latest API payloads locally to help debug field mapping without exposing credentials."""
    try:
        with open(os.path.join(APP_DIR, "trading212_last_sync_debug.json"), "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "positions": positions}, fh, indent=2, default=str)
    except Exception:
        pass


def trading212_get_settings(conn):
    row = conn.execute("SELECT * FROM trading212_settings WHERE id = 1").fetchone()
    if not row:
        conn.execute("""
            INSERT OR IGNORE INTO trading212_settings
            (id, environment, target_account_name, auto_update_account)
            VALUES (1, 'demo', 'Trading 212 ISA (Auto)', 1)
        """)
        conn.commit()
        row = conn.execute("SELECT * FROM trading212_settings WHERE id = 1").fetchone()
    return row


def trading212_log(conn, status, message):
    conn.execute(
        "INSERT INTO trading212_sync_log (status, message) VALUES (?, ?)",
        (status, message[:500]),
    )
    conn.commit()


def trading212_sync(conn, snapshot_fn=None):
    """Read-only sync: cash + open positions -> Trading 212 API-managed account value.

    Normalises GBX share prices into GBP before calculating values. GBX is pence, so
    1,234 GBX becomes £12.34 rather than £1,234.00.
    """
    settings = trading212_get_settings(conn)
    environment = settings["environment"]

    # The Trading 212 integration owns a read-only Account Balances row. Keep
    # the old setting forced on so all pages stay consistent after each sync.
    if "auto_update_account" in settings.keys() and int(settings["auto_update_account"] or 0) != 1:
        conn.execute("UPDATE trading212_settings SET auto_update_account = 1 WHERE id = 1")

    summary = trading212_api_get(environment, "/equity/account/summary", conn)
    positions = trading212_api_get(environment, "/equity/positions", conn)
    _debug_dump_trading212(summary, positions)

    if isinstance(positions, dict):
        positions_list = positions.get("items") or positions.get("data") or positions.get("positions") or []
    else:
        positions_list = positions or []

    # Account summary cash is nested under cash. Use available cash + cash held inside pies.
    cash = round(
        _first_number(summary, ["cash.availableToTrade", "availableToTrade"], 0.0)
        + _first_number(summary, ["cash.inPies", "inPies"], 0.0),
        2,
    )
    currency = _first_text(summary, ["currency", "accountCurrency", "baseCurrency"], "GBP")

    conn.execute("DELETE FROM trading212_holdings")
    holdings_value = 0.0

    for position in positions_list:
        ticker = _first_text(position, [
            "instrument.ticker",
            "ticker",
            "instrument.shortName",
            "instrument.name",
            "shortName",
            "name",
            "instrument.isin",
            "isin",
        ], "Unknown")
        display_name = _first_text(position, ["instrument.name", "instrument.shortName", "name", "shortName", "instrument.fullName"], ticker)
        quantity = _first_number(position, ["quantity", "qty", "shares"], 0.0)

        # Trading 212 can return UK-listed prices in GBX. GBX is pence, so prices must be /100
        # before calculating a GBP account value. Keep both raw and normalised values for debugging.
        raw_average_price, price_currency, average_price = _first_money_with_currency(
            position,
            ["averagePricePaid", "averagePrice", "avgPrice", "average_price", "price.average"],
            ["priceCurrency", "currentPriceCurrency", "instrument.currencyCode", "instrument.currency", "currency"],
            currency,
        )
        raw_current_price, price_currency, current_price = _first_money_with_currency(
            position,
            ["currentPrice", "price", "lastPrice", "marketPrice", "price.current"],
            ["priceCurrency", "currentPriceCurrency", "instrument.currencyCode", "instrument.currency", "currency"],
            price_currency,
        )

        pnl = _first_number(position, ["walletImpact.unrealizedProfitLoss", "ppl", "profitLoss", "pnl", "unrealizedPnl"], 0.0)

        # Prefer explicit account-currency value only when Trading 212 supplies one.
        # Otherwise calculate from quantity × normalised price so GBX does not inflate totals by 100x.
        explicit_value = _first_number(position, ["walletImpact.currentValue", "currentValue", "marketValue", "value"], 0.0)
        if explicit_value:
            current_value = explicit_value
        elif quantity and current_price:
            current_value = quantity * current_price
        else:
            current_value = 0.0

        holding_currency = _first_text(position, ["walletImpact.currency", "currency", "accountCurrency"], currency)
        current_value = round(current_value, 2)
        holdings_value += current_value
        conn.execute(
            """
            INSERT INTO trading212_holdings
            (ticker, name, quantity, average_price, current_price, average_price_raw, current_price_raw, price_currency, current_value, pnl, currency, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, display_name, quantity, average_price, current_price, raw_average_price, raw_current_price, price_currency, current_value, pnl, holding_currency, json.dumps(position)),
        )

    holdings_value = round(holdings_value, 2)
    # Avoid double-counting summary totalValue. Total = account-currency holdings + free/pie cash.
    portfolio_total = round(cash + holdings_value, 2)

    target = trading212_get_or_create_auto_account(conn)
    old_value = float(target["current_value"] or 0)
    delta = round(portfolio_total - old_value, 2)
    if delta:
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'value_update', ?, ?)",
            (target["id"], delta, f"Trading 212 API sync updated {TRADING212_AUTO_ACCOUNT_NAME} from {_format_money(old_value)} to {_format_money(portfolio_total)}"),
        )
    conn.execute(
        """
        UPDATE accounts
        SET current_value = ?,
            name = ?,
            account_type = ?,
            term_type = CASE
                WHEN term_type IS NULL OR term_type = '' THEN ?
                ELSE term_type
            END,
            source_provider = ?,
            is_auto_managed = 1,
            is_archived = 0,
            archived_at = NULL
        WHERE id = ?
        """,
        (
            portfolio_total,
            TRADING212_AUTO_ACCOUNT_NAME,
            TRADING212_AUTO_ACCOUNT_TYPE,
            TRADING212_AUTO_TERM_TYPE,
            TRADING212_PROVIDER,
            target["id"],
        ),
    )
    trading212_archive_duplicate_accounts(conn, target["id"])
    if snapshot_fn:
        snapshot_fn(conn)

    conn.execute(
        """
        UPDATE trading212_settings
        SET last_sync_at = CURRENT_TIMESTAMP,
            cash_value = ?,
            holdings_value = ?,
            portfolio_total = ?,
            rate_limit_reset_at = NULL
        WHERE id = 1
        """,
        (cash, holdings_value, portfolio_total),
    )
    trading212_log(conn, "success", f"Synced {len(positions_list)} positions. Cash {_format_money(cash)}. Holdings {_format_money(holdings_value)}. Total {_format_money(portfolio_total)}.")
    conn.commit()
    return {"cash": cash, "holdings_value": holdings_value, "portfolio_total": portfolio_total, "currency": currency, "positions_count": len(positions_list)}


