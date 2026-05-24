"""Property route blueprint for InvestHome."""

from flask import Blueprint, flash, render_template, request

from db import get_db


property_bp = Blueprint("property", __name__)


@property_bp.route("/property", methods=["GET", "POST"])
def property_page():
    conn = get_db()

    if request.method == "POST":
        home_value = float(request.form.get("home_value") or 0)
        mortgage_left = float(request.form.get("mortgage_left") or 0)
        include_in_net_worth = 1 if request.form.get("include_in_net_worth") == "1" else 0
        conn.execute(
            """
            INSERT OR REPLACE INTO property_settings (id, home_value, mortgage_left, include_in_net_worth, updated_at)
            VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (home_value, mortgage_left, include_in_net_worth),
        )
        conn.commit()
        flash("Property values updated.")

    prop = conn.execute("SELECT * FROM property_settings WHERE id = 1").fetchone()
    home_value = float(prop["home_value"] or 0) if prop else 0.0
    mortgage_left = float(prop["mortgage_left"] or 0) if prop else 0.0
    include_in_net_worth = bool(int(prop["include_in_net_worth"] or 0)) if prop and "include_in_net_worth" in prop.keys() else True
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
        include_in_net_worth=include_in_net_worth,
    )
