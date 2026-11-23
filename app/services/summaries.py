from datetime import datetime

from app.db import get_conn
from app.services.periods import to_db

FAR_FUTURE = "9999-12-31T00:00:00"


def _range(since: datetime, until: datetime = None):
    return to_db(since), (to_db(until) if until else FAR_FUTURE)


def summary_since(user_id: int, since: datetime, type_: str = "expense", until: datetime = None):
    """(rows by category, grand total) for entries with since <= created_at < until."""
    start, end = _range(since, until)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) as total, COUNT(*) as cnt FROM expenses "
            "WHERE user_id = ? AND type = ? AND created_at >= ? AND created_at < ? "
            "GROUP BY category ORDER BY total DESC",
            (user_id, type_, start, end),
        ).fetchall()
        total_row = conn.execute(
            "SELECT SUM(amount) as total FROM expenses "
            "WHERE user_id = ? AND type = ? AND created_at >= ? AND created_at < ?",
            (user_id, type_, start, end),
        ).fetchone()
        return rows, total_row["total"] or 0


def totals_since(user_id: int, since: datetime, until: datetime = None):
    """Returns (income_total, expense_total) for since <= created_at < until."""
    start, end = _range(since, until)
    with get_conn() as conn:
        totals = {}
        for type_ in ("income", "expense"):
            totals[type_] = conn.execute(
                "SELECT SUM(amount) as total FROM expenses "
                "WHERE user_id = ? AND type = ? AND created_at >= ? AND created_at < ?",
                (user_id, type_, start, end),
            ).fetchone()["total"] or 0
        return totals["income"], totals["expense"]
