import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "finance_bot.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                PRIMARY KEY (user_id, category)
            )
        """)


def add_expense(user_id: int, amount: float, category: str, note: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category.lower(), note, datetime.utcnow().isoformat()),
        )


def delete_expense(user_id: int, expense_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id)
        )
        return cur.rowcount > 0


def list_recent(user_id: int, limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, amount, category, note, created_at FROM expenses "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return rows


def summary_since(user_id: int, since: datetime):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) as total, COUNT(*) as cnt FROM expenses "
            "WHERE user_id = ? AND created_at >= ? GROUP BY category ORDER BY total DESC",
            (user_id, since.isoformat()),
        ).fetchall()
        total_row = conn.execute(
            "SELECT SUM(amount) as total FROM expenses WHERE user_id = ? AND created_at >= ?",
            (user_id, since.isoformat()),
        ).fetchone()
        grand_total = total_row["total"] or 0
        return rows, grand_total


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
