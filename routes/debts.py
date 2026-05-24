"""Debts routes for InvestHome.

This blueprint keeps the existing Debts page behaviour while moving the route
handlers out of app.py as the next low-risk v3 route extraction step.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import DEBT_TYPES
from db import get_db
from services.debts import debt_summary, normalise_debt_type
from utils import safe_float


debts_bp = Blueprint("debts", __name__)


@debts_bp.route("/debts")
def debts_page():
    conn = get_db()
    summary = debt_summary(conn)
    conn.close()
    return render_template(
        "debts.html",
        debts=summary["debt_rows"],
        total_debt=summary["total_debt"],
        ignored_debt=summary["ignored_debt"],
        planned_payment=summary["planned_payment"],
        minimum_payment=summary["minimum_payment"],
        highest_apr=summary["highest_apr"],
        payoff_months=summary["payoff_months"],
        payoff_status=summary.get("payoff_status", "none"),
        debt_types=DEBT_TYPES,
    )


@debts_bp.route("/debts/add", methods=["POST"])
def add_debt():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Debt name is required.")
        return redirect(url_for("debts.debts_page"))
    debt_type = normalise_debt_type(request.form.get("debt_type"))
    current_balance = max(safe_float(request.form.get("current_balance")), 0)
    apr = max(safe_float(request.form.get("apr")), 0)
    minimum_payment = max(safe_float(request.form.get("minimum_payment")), 0)
    planned_payment = max(safe_float(request.form.get("planned_payment")), 0)
    due_day_raw = request.form.get("due_day")
    due_day = int(float(due_day_raw)) if str(due_day_raw or "").strip() else None
    if due_day is not None:
        due_day = max(1, min(31, due_day))
    include_in_net_worth = 1 if request.form.get("include_in_net_worth") == "1" else 0
    note = request.form.get("note", "").strip()

    conn = get_db()
    conn.execute(
        """
        INSERT INTO debts
        (name, debt_type, current_balance, apr, minimum_payment, planned_payment, due_day, include_in_net_worth, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?)
        """,
        (name, debt_type, current_balance, apr, minimum_payment, planned_payment, due_day, include_in_net_worth, note),
    )
    conn.commit()
    conn.close()
    flash("Debt added.")
    return redirect(url_for("debts.debts_page"))


@debts_bp.route("/debts/update/<int:debt_id>", methods=["POST"])
def update_debt(debt_id):
    name = request.form.get("name", "").strip()
    if not name:
        flash("Debt name is required.")
        return redirect(url_for("debts.debts_page"))
    debt_type = normalise_debt_type(request.form.get("debt_type"))
    current_balance = max(safe_float(request.form.get("current_balance")), 0)
    apr = max(safe_float(request.form.get("apr")), 0)
    minimum_payment = max(safe_float(request.form.get("minimum_payment")), 0)
    planned_payment = max(safe_float(request.form.get("planned_payment")), 0)
    due_day_raw = request.form.get("due_day")
    due_day = int(float(due_day_raw)) if str(due_day_raw or "").strip() else None
    if due_day is not None:
        due_day = max(1, min(31, due_day))
    include_in_net_worth = 1 if request.form.get("include_in_net_worth") == "1" else 0
    status = request.form.get("status", "Active")
    if status not in {"Active", "Cleared"}:
        status = "Active"
    note = request.form.get("note", "").strip()

    conn = get_db()
    conn.execute(
        """
        UPDATE debts
        SET name = ?, debt_type = ?, current_balance = ?, apr = ?, minimum_payment = ?,
            planned_payment = ?, due_day = ?, include_in_net_worth = ?, status = ?, note = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (name, debt_type, current_balance, apr, minimum_payment, planned_payment, due_day, include_in_net_worth, status, note, debt_id),
    )
    conn.commit()
    conn.close()
    flash("Debt updated.")
    return redirect(url_for("debts.debts_page"))


@debts_bp.route("/debts/archive/<int:debt_id>", methods=["POST"])
def archive_debt(debt_id):
    conn = get_db()
    conn.execute("UPDATE debts SET status = 'Archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (debt_id,))
    conn.commit()
    conn.close()
    flash("Debt archived.")
    return redirect(url_for("debts.debts_page"))
