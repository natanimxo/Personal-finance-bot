from datetime import datetime

from app.db import get_conn
from app.services.periods import to_db


def get_budget(user_id: int, category: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT amount FROM budgets WHERE user_id = ? AND category = ?",
            (user_id, category.lower()),
        ).fetchone()
        return row["amount"] if row else None


def set_budget(user_id: int, category: str, amount: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO budgets (user_id, category, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, category) DO UPDATE SET amount = excluded.amount",
            (user_id, category.lower(), amount),
        )


def get_budgets(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT category, amount FROM budgets WHERE user_id = ?", (user_id,)
        ).fetchall()


def month_total_for_category(user_id: int, category: str, since: datetime):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(amount) as total FROM expenses "
            "WHERE user_id = ? AND category = ? AND type = 'expense' AND created_at >= ?",
            (user_id, category.lower(), to_db(since)),
        ).fetchone()
        return row["total"] or 0
