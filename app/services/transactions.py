from datetime import datetime, timezone

from app.db import get_conn


def add_expense(user_id: int, amount: float, category: str, note: str = "", type_: str = "expense", account: str = "cash") -> int:
    """Adds an income or expense entry and returns its id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, note, created_at, type, account) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, amount, category.lower(), note, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), type_, account),
        )
        return cur.lastrowid


def set_account(user_id: int, expense_id: int, account: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE expenses SET account = ? WHERE id = ? AND user_id = ?", (account, expense_id, user_id)
        )
        return cur.rowcount > 0


def get_entry(user_id: int, expense_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, amount, category, note, created_at, type, account FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()


def delete_expense(user_id: int, expense_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id)
        )
        return cur.rowcount > 0


def list_recent(user_id: int, limit: int = 10, type_: str = None):
    with get_conn() as conn:
        if type_:
            rows = conn.execute(
                "SELECT id, amount, category, note, created_at, type, account FROM expenses "
                "WHERE user_id = ? AND type = ? ORDER BY id DESC LIMIT ?",
                (user_id, type_, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, amount, category, note, created_at, type, account FROM expenses "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return rows
