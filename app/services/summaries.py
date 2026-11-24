"""Totals for a period. The bot's Summary, the recap and the Mini App's Home all use these."""
from datetime import date, datetime, timedelta

from app.db import get_conn
from app.services import accounts, budgets, catalog, periods
from app.services.periods import to_db

FAR_FUTURE = "9999-12-31T00:00:00"


def _range(since: datetime, until: datetime = None):
    return to_db(since), (to_db(until) if until else FAR_FUTURE)


def totals_minor(user_id: int, since: datetime, until: datetime = None):
    """(income, expenses) in cents for since <= occurred_at < until."""
    start, end = _range(since, until)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(CASE WHEN type = 'income' THEN amount_minor ELSE 0 END) AS income, "
            "SUM(CASE WHEN type = 'expense' THEN amount_minor ELSE 0 END) AS expense "
            "FROM expenses WHERE user_id = ? AND occurred_at >= ? AND occurred_at < ?",
            (user_id, start, end),
        ).fetchone()
    return row["income"] or 0, row["expense"] or 0


def by_category_minor(user_id: int, since: datetime, type_: str = "expense", until: datetime = None):
    start, end = _range(since, until)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT category, SUM(amount_minor) AS total_minor, COUNT(*) AS count FROM expenses "
            "WHERE user_id = ? AND type = ? AND occurred_at >= ? AND occurred_at < ? "
            "GROUP BY category ORDER BY total_minor DESC",
            (user_id, type_, start, end),
        )]


def period_bounds(period: str = "week", date_from: str = None, date_to: str = None, now: datetime = None):
    """(start, end, name). Custom from/to (local dates, inclusive) win over the period."""
    if date_from:
        d = date.fromisoformat(date_from)
        start = datetime(d.year, d.month, d.day, tzinfo=periods.tz())
        end = None
        if date_to:
            e = date.fromisoformat(date_to) + timedelta(days=1)
            end = datetime(e.year, e.month, e.day, tzinfo=periods.tz())
        return start, end, "custom"
    if period == "month":
        return periods.month_start(now), None, "month"
    return periods.week_start(now), None, "week"


@periods.in_user_zone
def summary(user_id: int, period: str = "week", date_from: str = None, date_to: str = None, now: datetime = None):
    start, end, name = period_bounds(period, date_from, date_to, now)
    income, expense = totals_minor(user_id, start, end)
    from app.services.categories import names
    labels = names(user_id, "expense")
    categories = by_category_minor(user_id, start, "expense", end)
    for c in categories:  # hidden categories included: their entries still count
        c["label"] = labels.get(c["category"]) or catalog.label_for(c["category"], "expense")
    from app.services.prefs import get_prefs
    return {
        "currency": get_prefs(user_id)["currency"],
        "period": name,
        "from": start.isoformat(),
        "to": end.isoformat() if end else None,
        "income_minor": income,
        "expense_minor": expense,
        "net_minor": income - expense,
        "savings_rate": periods.savings_rate(income, expense),
        "by_category": categories,
        "budgets": budgets.overview(user_id, now),
        "accounts": accounts.overview(user_id),
    }


# Older float shapes, used by the recap and existing tests.
def summary_since(user_id: int, since: datetime, type_: str = "expense", until: datetime = None):
    rows = [{"category": r["category"], "total": r["total_minor"] / 100, "cnt": r["count"]}
            for r in by_category_minor(user_id, since, type_, until)]
    return rows, sum(r["total"] for r in rows)


def totals_since(user_id: int, since: datetime, until: datetime = None):
    income, expense = totals_minor(user_id, since, until)
    return income / 100, expense / 100
