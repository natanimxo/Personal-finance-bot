from datetime import datetime

from app.db import get_conn


def summary_since(user_id: int, since: datetime, type_: str = "expense"):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) as total, COUNT(*) as cnt FROM expenses "
            "WHERE user_id = ? AND type = ? AND created_at >= ? GROUP BY category ORDER BY total DESC",
            (user_id, type_, since.isoformat()),
        ).fetchall()
        total_row = conn.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE user_id = ? AND type = ? AND created_at >= ?",
            (user_id, type_, since.isoformat()),
        ).fetchone()
        grand_total = total_row["total"] or 0
        return rows, grand_total


def totals_since(user_id: int, since: datetime):
    """Returns (income_total, expense_total) for the period."""
    with get_conn() as conn:
        income = conn.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE user_id = ? AND type = 'income' AND created_at >= ?",
            (user_id, since.isoformat()),
        ).fetchone()["total"] or 0
        expense = conn.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE user_id = ? AND type = 'expense' AND created_at >= ?",
            (user_id, since.isoformat()),
        ).fetchone()["total"] or 0
        return income, expense
