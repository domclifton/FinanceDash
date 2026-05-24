"""Progress page blueprint.

Structural refactor only: this module owns the Progress route while the
existing Progress calculation helper remains caller-supplied from app.py.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_db, set_setting


def create_progress_blueprint(progress_payload_fn):
    progress_bp = Blueprint("progress", __name__)

    @progress_bp.route("/progress", methods=["GET", "POST"])
    def progress_page():
        conn = get_db()
        if request.method == "POST":
            set_setting(conn, "progress_monthly_expenses", request.form.get("monthly_expenses", "0"))
            set_setting(conn, "progress_monthly_savings_goal", request.form.get("monthly_savings_goal", "500"))
            set_setting(conn, "progress_uk_net_worth_benchmark", request.form.get("uk_net_worth_benchmark", "293700"))
            set_setting(conn, "progress_uk_savings_rate_benchmark", request.form.get("uk_savings_rate_benchmark", "10"))
            conn.commit()
            flash("Progress settings saved.")
            conn.close()
            return redirect(url_for("progress.progress_page"))

        payload = progress_payload_fn(conn)
        conn.close()
        return render_template("progress.html", **payload)

    return progress_bp
