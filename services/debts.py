"""Debt domain helpers for InvestHome."""

import math

from config import DEBT_TYPES
from utils import safe_float


def normalise_debt_type(value):
    """Return a valid debt type, falling back to Other for unknown values."""
    value = (value or "Other").strip()
    return value if value in DEBT_TYPES else "Other"


def payoff_months_with_interest(balance, annual_apr_pct, monthly_payment):
    """Estimate payoff months using fixed monthly payments and APR.

    Returns None when the payment is missing or too low to reduce the balance.
    This is an estimate only; it does not model fees, promotional rates, changing
    minimum payments or extra ad-hoc repayments.
    """
    balance = max(safe_float(balance), 0)
    annual_apr_pct = max(safe_float(annual_apr_pct), 0)
    monthly_payment = max(safe_float(monthly_payment), 0)

    if balance <= 0:
        return 0
    if monthly_payment <= 0:
        return None

    monthly_rate = annual_apr_pct / 100 / 12
    if monthly_rate <= 0:
        return max(1, math.ceil(balance / monthly_payment))

    monthly_interest = balance * monthly_rate
    if monthly_payment <= monthly_interest:
        return None

    months = math.log(monthly_payment / (monthly_payment - monthly_interest)) / math.log(1 + monthly_rate)
    return max(1, math.ceil(months))


def debt_summary(conn):
    """Return current debt totals for the self-hosted single-user dashboard."""
    rows = conn.execute(
        """
        SELECT *
        FROM debts
        WHERE COALESCE(status, 'Active') != 'Archived'
        ORDER BY current_balance DESC, name
        """
    ).fetchall()
    active_rows = [row for row in rows if str(row["status"] or "Active") != "Cleared" or safe_float(row["current_balance"]) > 0]
    included = [row for row in active_rows if int(row["include_in_net_worth"] or 0) == 1]
    total_debt = round(sum(max(safe_float(row["current_balance"]), 0) for row in included), 2)
    ignored_debt = round(sum(max(safe_float(row["current_balance"]), 0) for row in active_rows if int(row["include_in_net_worth"] or 0) != 1), 2)
    planned_payment = round(sum(safe_float(row["planned_payment"]) for row in included), 2)
    minimum_payment = round(sum(safe_float(row["minimum_payment"]) for row in included), 2)
    highest_apr = max([safe_float(row["apr"]) for row in included] or [0])

    payoff_months = None
    payoff_status = "none"
    if total_debt > 0:
        included_with_balance = [row for row in included if safe_float(row["current_balance"]) > 0]
        payoff_estimates = [
            payoff_months_with_interest(row["current_balance"], row["apr"], row["planned_payment"])
            for row in included_with_balance
        ]
        if not included_with_balance:
            payoff_status = "none"
        elif any(months is None for months in payoff_estimates):
            payoff_status = "unreachable"
        else:
            payoff_months = max(payoff_estimates or [0])
            payoff_status = "ok" if payoff_months else "none"

    return {
        "debt_rows": rows,
        "active_debt_rows": active_rows,
        "total_debt": total_debt,
        "ignored_debt": ignored_debt,
        "planned_payment": planned_payment,
        "minimum_payment": minimum_payment,
        "highest_apr": round(highest_apr, 2),
        "payoff_months": payoff_months,
        "payoff_status": payoff_status,
        "debt_count": len(included),
    }
