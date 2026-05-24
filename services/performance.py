"""Performance and chart calculation services for InvestHome.

Extracted during the v3.0.0 backend refactor. This module is intentionally
route-free and Flask-free; callers pass in an open SQLite connection and any
optional side-effect callbacks needed to preserve legacy behaviour.
"""

from bisect import bisect_right
from datetime import date


def performance_rows(conn, pension_only=False, sync_bullion_fn=None):
    if sync_bullion_fn is not None:
        sync_bullion_fn(conn)
    if pension_only:
        accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND COALESCE(is_archived, 0) = 0 AND COALESCE(term_type, '') != 'Ignore' AND account_type = 'Pension' ORDER BY account_type, name").fetchall()
    else:
        accounts = conn.execute("SELECT * FROM accounts WHERE include_in_net_worth = 1 AND COALESCE(is_archived, 0) = 0 AND COALESCE(term_type, '') != 'Ignore' AND account_type != 'Pension' ORDER BY account_type, name").fetchall()
    rows = []
    total_current = total_contributions = total_growth = 0.0

    for account in accounts:
        current = float(account["current_value"] or 0)

        # Use the same contribution/cost-basis baseline as the performance charts.
        # This prevents imported/opening balances from being counted as growth on
        # the dashboard when no matching add/remove transaction exists yet.
        if account["account_type"] == "Physical Bullion":
            bullion_cost = conn.execute("SELECT COALESCE(SUM(purchase_price), 0) AS cost FROM bullion").fetchone()["cost"]
            contributions = float(bullion_cost or 0)
        else:
            contributions = _performance_contribution_baseline(conn, account)

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
          AND COALESCE(a.term_type, '') != 'Ignore'
          AND COALESCE(a.is_archived, 0) = 0
        GROUP BY substr(t.created_at, 1, 7)
        ORDER BY month
        """
    ).fetchall()
    return rows



def _nice_axis_max(value):
    """Round a chart maximum up to a clean 1/2/5/10 style interval."""
    import math

    value = float(value or 0)
    if value <= 0:
        return 1.0

    # Add headroom first so the highest point is not pinned to the top border.
    value *= 1.12
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)

    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10

    return nice_fraction * (10 ** exponent)


def _svg_chart_payload(labels, contribution_points, value_points):
    """Create a non-distorted server-rendered SVG line chart for performance pages."""
    width = 1200
    height = 320
    left = 82
    right = 72
    top = 34
    bottom = 62
    plot_w = width - left - right
    plot_h = height - top - bottom

    all_values = [float(v or 0) for v in contribution_points + value_points]
    max_y = _nice_axis_max(max(all_values + [1]))
    min_y = 0

    def x_pos(i):
        if len(labels) <= 1:
            return left + (plot_w / 2)
        return left + (i / (len(labels) - 1)) * plot_w

    def y_pos(v):
        return top + ((max_y - float(v or 0)) / (max_y - min_y)) * plot_h

    contribution_xy = [(x_pos(i), y_pos(v)) for i, v in enumerate(contribution_points)]
    value_xy = [(x_pos(i), y_pos(v)) for i, v in enumerate(value_points)]

    contribution_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in contribution_xy)
    value_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in value_xy)
    fill_polygon = ""
    if len(value_xy) >= 2 and len(contribution_xy) >= 2:
        fill_polygon = " ".join(f"{x:.1f},{y:.1f}" for x, y in value_xy + list(reversed(contribution_xy)))

    ticks = []
    tick_count = 5
    for i in range(tick_count):
        # Highest label at the top, zero at the bottom.
        val = max_y - (max_y * i / (tick_count - 1))
        y = y_pos(val)
        ticks.append({"y": round(y, 1), "label": f"£{val:,.0f}"})

    x_ticks = []
    if labels:
        if len(labels) == 1:
            indexes = [0]
        elif len(labels) <= 6:
            indexes = list(range(len(labels)))
        else:
            indexes = sorted(set([0, len(labels)//4, len(labels)//2, (len(labels)*3)//4, len(labels)-1]))
        for i in indexes:
            if len(labels) == 1:
                anchor = "middle"
            elif i == 0:
                anchor = "start"
            elif i == len(labels) - 1:
                anchor = "end"
            else:
                anchor = "middle"
            x_ticks.append({"x": round(x_pos(i), 1), "label": labels[i], "anchor": anchor})

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


def _latest_snapshot_value(conn, account_id, snap_date):
    """Return latest known account value at or before snap_date."""
    row = conn.execute(
        """
        SELECT value
        FROM snapshots
        WHERE account_id = ?
          AND date(snapshot_date) <= date(?)
        ORDER BY date(snapshot_date) DESC, id DESC
        LIMIT 1
        """,
        (account_id, snap_date),
    ).fetchone()
    return float(row["value"] or 0) if row else 0.0


def _first_positive_snapshot(conn, account_id, snap_date=None):
    """Return the first positive snapshot for an account, optionally bounded by date."""
    params = [account_id]
    date_filter = ""
    if snap_date is not None:
        date_filter = "AND date(snapshot_date) <= date(?)"
        params.append(snap_date)

    return conn.execute(
        f"""
        SELECT snapshot_date, value
        FROM snapshots
        WHERE account_id = ?
          AND COALESCE(value, 0) > 0
          {date_filter}
        ORDER BY date(snapshot_date), id
        LIMIT 1
        """,
        params,
    ).fetchone()


def _transaction_contributions(conn, account_id, snap_date=None, after_date=None):
    """Return add/remove transaction total for one account within optional date bounds."""
    params = [account_id]
    filters = ["account_id = ?", "transaction_type IN ('add', 'remove')"]

    if snap_date is not None:
        filters.append("date(created_at) <= date(?)")
        params.append(snap_date)
    if after_date is not None:
        filters.append("date(created_at) > date(?)")
        params.append(after_date)

    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE {' AND '.join(filters)}
        """,
        params,
    ).fetchone()
    return float(row["total"] or 0)


def _performance_contribution_baseline(conn, account, snap_date=None):
    """
    Return the contribution/cost-basis line for performance charts.

    Older app versions and API syncs could create/update a current value without
    a matching starting contribution transaction. In that situation, using only
    add/remove transactions makes the first imported balance appear as growth.
    For non-LISA long-term accounts, treat the first positive snapshot as the
    opening baseline whenever it is larger than the explicit contributions known
    at that point. Lifetime ISA keeps explicit contributions only, so any real
    bonus/value change recorded later via Update Total Value shows as growth.
    """
    account_id = account["id"]
    category = account["account_type"]

    explicit_total = _transaction_contributions(conn, account_id, snap_date=snap_date)

    # LISA bonus/value changes are intentionally not counted as contributions.
    if category == "Lifetime ISA":
        return explicit_total

    first_snapshot = _first_positive_snapshot(conn, account_id, snap_date=snap_date)
    if not first_snapshot:
        # If an account has a value but no snapshots yet, avoid showing the entire
        # opening balance as growth. This mostly protects fresh imports.
        if snap_date is None and explicit_total == 0 and float(account["current_value"] or 0) > 0:
            return float(account["current_value"] or 0)
        return explicit_total

    first_date = first_snapshot["snapshot_date"]
    first_value = float(first_snapshot["value"] or 0)
    explicit_at_first = _transaction_contributions(conn, account_id, snap_date=first_date)

    # If first snapshot is larger than known money-in at that time, treat that
    # first snapshot as the opening baseline, then add later deposits/withdrawals.
    if first_value > explicit_at_first + 0.01:
        after_first = _transaction_contributions(conn, account_id, snap_date=snap_date, after_date=first_date)
        return first_value + after_first

    return explicit_total


def _combined_contributions_for_accounts(conn, accounts, snap_date=None):
    return sum(_performance_contribution_baseline(conn, account, snap_date=snap_date) for account in accounts)


def _fetch_snapshot_labels_for_accounts(conn, account_ids):
    """Return ordered snapshot dates for a group of accounts using one DB query."""
    if not account_ids:
        return []

    placeholders = ",".join("?" for _ in account_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT date(snapshot_date) AS snapshot_date
        FROM snapshots
        WHERE account_id IN ({placeholders})
        ORDER BY date(snapshot_date)
        """,
        account_ids,
    ).fetchall()
    return [row["snapshot_date"] for row in rows]


def _bulk_latest_snapshot_totals(conn, account_ids, labels):
    """Return combined latest-known snapshot totals for every label without per-point DB calls."""
    if not account_ids or not labels:
        return []

    placeholders = ",".join("?" for _ in account_ids)
    max_label = max(labels)
    rows = conn.execute(
        f"""
        SELECT account_id, date(snapshot_date) AS snapshot_date, value
        FROM snapshots
        WHERE account_id IN ({placeholders})
          AND date(snapshot_date) <= date(?)
        ORDER BY account_id, date(snapshot_date), id
        """,
        [*account_ids, max_label],
    ).fetchall()

    snapshots_by_account = {account_id: [] for account_id in account_ids}
    for row in rows:
        snapshots_by_account.setdefault(row["account_id"], []).append(
            (row["snapshot_date"], float(row["value"] or 0))
        )

    pointers = {account_id: 0 for account_id in account_ids}
    latest_values = {account_id: 0.0 for account_id in account_ids}
    totals = []

    for label in labels:
        total = 0.0
        for account_id in account_ids:
            account_rows = snapshots_by_account.get(account_id, [])
            pointer = pointers.get(account_id, 0)
            latest = latest_values.get(account_id, 0.0)

            while pointer < len(account_rows) and account_rows[pointer][0] <= label:
                latest = account_rows[pointer][1]
                pointer += 1

            pointers[account_id] = pointer
            latest_values[account_id] = latest
            total += latest

        totals.append(round(total, 2))

    return totals


def _bulk_contribution_baselines(conn, accounts, labels):
    """Return combined contribution/opening-baseline totals for every label using bulk reads.

    This mirrors _performance_contribution_baseline(), but it preloads transactions
    and first positive snapshots for all accounts so the performance page does not
    run one or more SQL queries per account per chart date.
    """
    if not accounts:
        return [], 0.0

    labels = list(labels or [])
    account_ids = [account["id"] for account in accounts]
    placeholders = ",".join("?" for _ in account_ids)

    tx_rows = conn.execute(
        f"""
        SELECT account_id, date(created_at) AS tx_date, amount
        FROM transactions
        WHERE account_id IN ({placeholders})
          AND transaction_type IN ('add', 'remove')
        ORDER BY account_id, date(created_at), id
        """,
        account_ids,
    ).fetchall()

    snapshot_rows = conn.execute(
        f"""
        SELECT account_id, date(snapshot_date) AS snapshot_date, value
        FROM snapshots
        WHERE account_id IN ({placeholders})
          AND COALESCE(value, 0) > 0
        ORDER BY account_id, date(snapshot_date), id
        """,
        account_ids,
    ).fetchall()

    transactions_by_account = {account_id: [] for account_id in account_ids}
    for row in tx_rows:
        transactions_by_account.setdefault(row["account_id"], []).append(
            (row["tx_date"], float(row["amount"] or 0))
        )

    first_positive_snapshot_by_account = {}
    for row in snapshot_rows:
        account_id = row["account_id"]
        if account_id not in first_positive_snapshot_by_account:
            first_positive_snapshot_by_account[account_id] = (
                row["snapshot_date"],
                float(row["value"] or 0),
            )

    combined_by_label = [0.0 for _ in labels]
    current_total = 0.0

    for account in accounts:
        account_id = account["id"]
        category = account["account_type"]
        transactions = transactions_by_account.get(account_id, [])
        tx_dates = [tx_date for tx_date, _amount in transactions]
        tx_prefix = [0.0]
        for _tx_date, amount in transactions:
            tx_prefix.append(tx_prefix[-1] + amount)

        def tx_sum_upto(snap_date):
            index = bisect_right(tx_dates, snap_date)
            return tx_prefix[index]

        def tx_sum_after_until(after_date, snap_date=None):
            start_index = bisect_right(tx_dates, after_date)
            end_index = len(tx_dates) if snap_date is None else bisect_right(tx_dates, snap_date)
            return tx_prefix[end_index] - tx_prefix[start_index]

        first_snapshot = first_positive_snapshot_by_account.get(account_id)

        def baseline_for_date(snap_date=None):
            explicit_total = tx_prefix[-1] if snap_date is None else tx_sum_upto(snap_date)

            # LISA bonus/value changes are intentionally not counted as contributions.
            if category == "Lifetime ISA":
                return explicit_total

            if not first_snapshot or (snap_date is not None and first_snapshot[0] > snap_date):
                # Match _performance_contribution_baseline() for current/no-snapshot imports.
                if snap_date is None and explicit_total == 0 and float(account["current_value"] or 0) > 0:
                    return float(account["current_value"] or 0)
                return explicit_total

            first_date, first_value = first_snapshot
            explicit_at_first = tx_sum_upto(first_date)

            if first_value > explicit_at_first + 0.01:
                return first_value + tx_sum_after_until(first_date, snap_date)

            return explicit_total

        for index, label in enumerate(labels):
            combined_by_label[index] += baseline_for_date(label)

        current_total += baseline_for_date(None)

    return [round(value, 2) for value in combined_by_label], round(current_total, 2)


def _build_combined_category_chart(conn, title, category_name):
    """Build a contribution/current-value chart for every active account in one account category."""
    accounts = conn.execute(
        """
        SELECT *
        FROM accounts
        WHERE include_in_net_worth = 1
          AND COALESCE(is_archived, 0) = 0
          AND COALESCE(term_type, '') != 'Ignore'
          AND account_type = ?
        ORDER BY name, id
        """,
        (category_name,),
    ).fetchall()

    account_ids = [a["id"] for a in accounts]
    account_name = f"All {category_name} accounts" if len(accounts) != 1 else accounts[0]["name"]

    if not account_ids:
        return {
            "title": title,
            "account_name": category_name,
            "current_value": 0,
            "current_contributions": 0,
            "current_growth": 0,
            "current_growth_pct": 0,
            "svg": _svg_chart_payload([], [], []),
        }

    labels = _fetch_snapshot_labels_for_accounts(conn, account_ids)
    if not labels:
        labels = [date.today().isoformat()]

    contribution_points, current_contributions = _bulk_contribution_baselines(conn, accounts, labels)
    value_points = _bulk_latest_snapshot_totals(conn, account_ids, labels)

    current_value = round(sum(float(a["current_value"] or 0) for a in accounts), 2)
    current_growth = round(current_value - current_contributions, 2)
    current_growth_pct = round((current_growth / current_contributions * 100), 2) if current_contributions else 0

    # Make the final point match the live account total if today's snapshot has not yet been taken.
    if labels:
        value_points[-1] = current_value
        contribution_points[-1] = current_contributions

    return {
        "title": title,
        "account_name": account_name,
        "current_value": current_value,
        "current_contributions": current_contributions,
        "current_growth": current_growth,
        "current_growth_pct": current_growth_pct,
        "svg": _svg_chart_payload(labels, contribution_points, value_points),
    }


def _build_single_category_chart(conn, title, category_name):
    """Build a chart for an account category that normally has one active account."""
    return _build_combined_category_chart(conn, title, category_name)


def _build_combined_long_term_chart(conn):
    """Build one combined long-term chart across S&S ISA, Lifetime ISA, and Pension categories."""
    category_names = ["Stocks and Shares ISA", "Lifetime ISA", "Pension"]
    placeholders = ",".join("?" for _ in category_names)

    accounts = conn.execute(
        f"""
        SELECT *
        FROM accounts
        WHERE include_in_net_worth = 1
          AND COALESCE(is_archived, 0) = 0
          AND COALESCE(term_type, '') != 'Ignore'
          AND account_type IN ({placeholders})
          AND (
                COALESCE(current_value, 0) != 0
                OR EXISTS (
                    SELECT 1 FROM transactions t WHERE t.account_id = accounts.id
                )
                OR EXISTS (
                    SELECT 1 FROM snapshots s WHERE s.account_id = accounts.id
                )
          )
        ORDER BY account_type, name, id
        """,
        category_names,
    ).fetchall()

    account_ids = [a["id"] for a in accounts]
    if not account_ids:
        return {
            "title": "Combined Long Term Over Time",
            "account_name": "Stocks and Shares ISA + Lifetime ISA + Pension",
            "current_value": 0,
            "current_contributions": 0,
            "current_growth": 0,
            "current_growth_pct": 0,
            "svg": _svg_chart_payload([], [], []),
        }

    labels = _fetch_snapshot_labels_for_accounts(conn, account_ids)
    if not labels:
        labels = [date.today().isoformat()]

    contribution_points, current_contributions = _bulk_contribution_baselines(conn, accounts, labels)
    value_points = _bulk_latest_snapshot_totals(conn, account_ids, labels)

    current_value = round(sum(float(a["current_value"] or 0) for a in accounts), 2)
    current_growth = round(current_value - current_contributions, 2)
    current_growth_pct = round((current_growth / current_contributions * 100), 2) if current_contributions else 0

    if labels:
        value_points[-1] = current_value
        contribution_points[-1] = current_contributions

    return {
        "title": "Combined Long Term Over Time",
        "account_name": "Stocks and Shares ISA + Lifetime ISA + Pension",
        "current_value": current_value,
        "current_contributions": current_contributions,
        "current_growth": current_growth,
        "current_growth_pct": current_growth_pct,
        "svg": _svg_chart_payload(labels, contribution_points, value_points),
    }


def performance_chart_series(conn):
    """Build over-time charts for key long-term categories.

    Stocks and Shares ISA is intentionally combined by account category, so multiple
    S&S ISA accounts roll into one chart.
    Blue shows cumulative contributions/opening baseline.
    Green shows current value. When green is above blue, the account/category is in profit.
    """
    return [
        _build_combined_long_term_chart(conn),
        _build_combined_category_chart(conn, "Stocks and Shares ISA Over Time", "Stocks and Shares ISA"),
        _build_single_category_chart(conn, "Lifetime ISA Over Time", "Lifetime ISA"),
        _build_single_category_chart(conn, "Pension Over Time", "Pension"),
    ]


