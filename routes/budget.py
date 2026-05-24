"""Budget routes for InvestHome.

Structural refactor only: route handlers are moved out of app.py with existing
public URLs and behaviour preserved.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_db


budget_bp = Blueprint("budget", __name__)


@budget_bp.route("/budget")
def budget():
    """Combined budget calculator with Solo/Couple mode selector."""
    mode = request.args.get("mode", "solo").lower().strip()
    if mode not in {"solo", "couple"}:
        mode = "solo"

    conn = get_db()
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO budget_settings (id, income) VALUES (1, 0)")
    cur.execute("""
        INSERT OR IGNORE INTO couple_budget_settings
        (id, person_one_name, person_one_income, person_two_name, person_two_income)
        VALUES (1, 'Person 1', 0, 'Person 2', 0)
    """)
    conn.commit()

    solo_income = cur.execute("SELECT income FROM budget_settings WHERE id = 1").fetchone()["income"]
    solo_items = cur.execute("SELECT * FROM budget_items ORDER BY id").fetchall()
    solo_total_outgoings = sum(float(item["amount"] or 0) for item in solo_items)
    solo_floating_left = float(solo_income or 0) - solo_total_outgoings

    couple_settings = cur.execute("SELECT * FROM couple_budget_settings WHERE id = 1").fetchone()
    couple_items = cur.execute("SELECT * FROM couple_budget_items ORDER BY stream, id").fetchall()
    person_one_income = float(couple_settings["person_one_income"] or 0)
    person_two_income = float(couple_settings["person_two_income"] or 0)
    combined_income = person_one_income + person_two_income
    couple_total_outgoings = sum(float(item["amount"] or 0) for item in couple_items)
    couple_floating_left = combined_income - couple_total_outgoings

    stream_totals = {"Joint": 0.0, "Person 1": 0.0, "Person 2": 0.0}
    for item in couple_items:
        stream = item["stream"] or "Joint"
        stream_totals[stream] = stream_totals.get(stream, 0.0) + float(item["amount"] or 0)

    conn.close()
    return render_template(
        "budget.html",
        mode=mode,
        solo_income=solo_income,
        solo_items=solo_items,
        solo_total_outgoings=solo_total_outgoings,
        solo_floating_left=solo_floating_left,
        couple_settings=couple_settings,
        couple_items=couple_items,
        person_one_income=person_one_income,
        person_two_income=person_two_income,
        combined_income=combined_income,
        couple_total_outgoings=couple_total_outgoings,
        couple_floating_left=couple_floating_left,
        stream_totals=stream_totals,
    )


@budget_bp.route("/budget/solo")
def budget_solo():
    return redirect(url_for("budget.budget", mode="solo"))


@budget_bp.route("/budget/couple")
def budget_couple():
    return redirect(url_for("budget.budget", mode="couple"))


@budget_bp.route("/budget/solo/income", methods=["POST"])
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
    return redirect(url_for("budget.budget", mode="solo"))


@budget_bp.route("/budget/solo/add", methods=["POST"])
def add_budget_item():
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    if not name:
        flash("Budget topic name is required.")
        return redirect(url_for("budget.budget", mode="solo"))

    conn = get_db()
    conn.execute("INSERT INTO budget_items (name, amount) VALUES (?, ?)", (name, amount))
    conn.commit()
    conn.close()
    flash("Solo budget item added.")
    return redirect(url_for("budget.budget", mode="solo"))


@budget_bp.route("/budget/solo/update/<int:item_id>", methods=["POST"])
def update_budget_item(item_id):
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    conn = get_db()
    conn.execute("UPDATE budget_items SET name = ?, amount = ? WHERE id = ?", (name, amount, item_id))
    conn.commit()
    conn.close()
    flash("Solo budget item updated.")
    return redirect(url_for("budget.budget", mode="solo"))


@budget_bp.route("/budget/solo/delete/<int:item_id>", methods=["POST"])
def delete_budget_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM budget_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Solo budget item deleted.")
    return redirect(url_for("budget.budget", mode="solo"))


@budget_bp.route("/budget/couple/income", methods=["POST"])
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
    return redirect(url_for("budget.budget", mode="couple"))


@budget_bp.route("/budget/couple/add", methods=["POST"])
def add_couple_budget_item():
    stream = request.form.get("stream", "Joint").strip() or "Joint"
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    if not name:
        flash("Budget topic name is required.")
        return redirect(url_for("budget.budget", mode="couple"))

    conn = get_db()
    conn.execute("INSERT INTO couple_budget_items (stream, name, amount) VALUES (?, ?, ?)", (stream, name, amount))
    conn.commit()
    conn.close()
    flash("Couple budget item added.")
    return redirect(url_for("budget.budget", mode="couple"))


@budget_bp.route("/budget/couple/update/<int:item_id>", methods=["POST"])
def update_couple_budget_item(item_id):
    stream = request.form.get("stream", "Joint").strip() or "Joint"
    name = request.form.get("name", "").strip()
    amount = float(request.form.get("amount") or 0)
    conn = get_db()
    conn.execute("UPDATE couple_budget_items SET stream = ?, name = ?, amount = ? WHERE id = ?", (stream, name, amount, item_id))
    conn.commit()
    conn.close()
    flash("Couple budget item updated.")
    return redirect(url_for("budget.budget", mode="couple"))


@budget_bp.route("/budget/couple/delete/<int:item_id>", methods=["POST"])
def delete_couple_budget_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM couple_budget_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Couple budget item deleted.")
    return redirect(url_for("budget.budget", mode="couple"))
