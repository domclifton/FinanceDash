"""Accounts and transaction routes for InvestHome.

Structural refactor only: these routes keep the same public URLs and
behaviour while moving account handlers out of app.py.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import TERM_TYPES
from db import default_term_for_account, get_account_types, get_db
from services.performance import monthly_performance, performance_chart_series, performance_rows
from services.trading212 import is_auto_managed_account, trading212_reconcile_auto_account_from_cache


def create_accounts_blueprint(take_snapshot_fn, sync_bullion_fn, is_lifetime_isa_fn, format_money_fn):
    accounts_bp = Blueprint("accounts", __name__)

    @accounts_bp.route("/accounts")
    def accounts():
        conn = get_db()
        trading212_reconcile_auto_account_from_cache(conn, snapshot_fn=take_snapshot_fn)
        sync_bullion_fn(conn)
        rows = conn.execute("SELECT * FROM accounts WHERE COALESCE(is_archived, 0) = 0 ORDER BY account_type, name").fetchall()
        archived_accounts = conn.execute("SELECT * FROM accounts WHERE COALESCE(is_archived, 0) = 1 ORDER BY archived_at DESC, account_type, name").fetchall()
        account_types = get_account_types(conn)
        conn.close()
        return render_template("accounts.html", accounts=rows, archived_accounts=archived_accounts, account_types=account_types, term_types=TERM_TYPES)

    @accounts_bp.route("/accounts/add", methods=["POST"])
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
        take_snapshot_fn(conn)
        conn.close()
        flash("Account added.")
        return redirect(url_for("accounts.accounts"))

    @accounts_bp.route("/transaction/add", methods=["POST"])
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
            return redirect(url_for("accounts.accounts"))
        if account["account_type"] == "Physical Bullion":
            conn.close()
            flash("Physical Bullion is calculated from bullion holdings. Add/remove items from the Bullion page.")
            return redirect(url_for("bullion"))
        if is_auto_managed_account(account):
            conn.close()
            flash("This account is managed automatically by an external provider and cannot be edited manually.")
            return redirect(url_for("accounts.accounts"))

        is_lisa_deposit = transaction_type == "add" and is_lifetime_isa_fn(account)

        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, ?, ?, ?)",
            (account_id, transaction_type, signed_amount, note),
        )

        conn.execute("UPDATE accounts SET current_value = current_value + ? WHERE id = ?", (signed_amount, account_id))
        conn.commit()
        take_snapshot_fn(conn)
        conn.close()

        if is_lisa_deposit:
            flash("Lifetime ISA deposit saved. The 25% government bonus has not been added automatically; update the total value when the bonus actually arrives.")
        else:
            flash("Transaction saved.")
        return redirect(request.referrer or url_for("dashboard"))

    @accounts_bp.route("/transactions")
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
        editable_accounts = conn.execute("SELECT * FROM accounts WHERE COALESCE(is_archived, 0) = 0 AND account_type != 'Physical Bullion' AND COALESCE(is_auto_managed, 0) = 0 AND COALESCE(source_provider, '') = '' ORDER BY name").fetchall()
        conn.close()
        return render_template("transactions.html", transactions=rows, accounts=editable_accounts)

    @accounts_bp.route("/accounts/update-name", methods=["POST"])
    def update_account_name():
        account_id = int(request.form["account_id"])
        new_name = request.form.get("name", "").strip()

        if not new_name:
            flash("Account name cannot be blank.")
            return redirect(url_for("accounts.accounts"))

        conn = get_db()
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not account:
            conn.close()
            flash("Account not found.")
            return redirect(url_for("accounts.accounts"))
        if is_auto_managed_account(account):
            conn.close()
            flash("Auto-managed account names are controlled by the provider integration.")
            return redirect(url_for("accounts.accounts"))

        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (new_name, account_id))
        conn.commit()
        conn.close()
        flash("Account name updated.")
        return redirect(url_for("accounts.accounts"))

    @accounts_bp.route("/accounts/update-term", methods=["POST"])
    def update_account_term():
        account_id = int(request.form["account_id"])
        term_type = request.form.get("term_type", "").strip()

        if term_type not in TERM_TYPES:
            flash("Invalid term type selected.")
            return redirect(url_for("accounts.accounts"))

        conn = get_db()
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not account:
            conn.close()
            flash("Account not found.")
            return redirect(url_for("accounts.accounts"))
        # Auto-managed accounts keep their provider-owned value, but the dashboard bucket
        # is still a local preference. Allow changing the Type dropdown for rows such
        # as Trading 212 ISA (Auto).
        conn.execute("UPDATE accounts SET term_type = ? WHERE id = ?", (term_type, account_id))
        conn.commit()
        conn.close()
        flash("Account type updated.")
        return redirect(url_for("accounts.accounts"))

    @accounts_bp.route("/accounts/update-value", methods=["POST"])
    def update_account_value():
        account_id = int(request.form["account_id"])
        new_value = float(request.form["new_value"])
        note = request.form.get("note", "").strip()

        conn = get_db()
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not account:
            conn.close()
            flash("Account not found.")
            return redirect(url_for("accounts.accounts"))

        if account["account_type"] == "Physical Bullion":
            conn.close()
            flash("Physical Bullion is calculated from bullion holdings and metal prices.")
            return redirect(url_for("bullion"))
        if is_auto_managed_account(account):
            conn.close()
            flash("This account is managed automatically by an external provider and cannot be edited manually.")
            return redirect(url_for("accounts.accounts"))

        old_value = float(account["current_value"] or 0)
        delta = round(new_value - old_value, 2)
        if delta == 0:
            conn.close()
            flash("Value unchanged.")
            return redirect(request.referrer or url_for("accounts.accounts"))

        clean_note = note or f"Value updated from {format_money_fn(old_value)} to {format_money_fn(new_value)}"
        conn.execute(
            "INSERT INTO transactions (account_id, transaction_type, amount, note) VALUES (?, 'value_update', ?, ?)",
            (account_id, delta, clean_note),
        )
        conn.execute("UPDATE accounts SET current_value = ? WHERE id = ?", (new_value, account_id))
        conn.commit()
        take_snapshot_fn(conn)
        conn.close()
        flash("Asset value updated.")
        return redirect(request.referrer or url_for("accounts.accounts"))

    @accounts_bp.route("/accounts/archive", methods=["POST"])
    def archive_account():
        account_id = int(request.form["account_id"])
        conn = get_db()
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not account:
            conn.close()
            flash("Account not found.")
            return redirect(url_for("accounts.accounts"))
        if account["account_type"] == "Physical Bullion":
            conn.close()
            flash("Physical Bullion is calculated from bullion holdings and cannot be deleted from Accounts.")
            return redirect(url_for("accounts.accounts"))
        if is_auto_managed_account(account):
            conn.close()
            flash("This account is managed automatically. Disable the integration if you no longer want it refreshed.")
            return redirect(url_for("accounts.accounts"))

        conn.execute(
            "UPDATE accounts SET is_archived = 1, archived_at = CURRENT_TIMESTAMP WHERE id = ?",
            (account_id,),
        )
        conn.commit()
        conn.close()
        flash("Account deleted from the active list. Transactions and snapshots were kept for statistics/history.")
        return redirect(url_for("accounts.accounts"))

    @accounts_bp.route("/accounts/restore", methods=["POST"])
    def restore_account():
        account_id = int(request.form["account_id"])
        conn = get_db()
        conn.execute("UPDATE accounts SET is_archived = 0, archived_at = NULL WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()
        flash("Account restored.")
        return redirect(url_for("accounts.accounts"))

    return accounts_bp
