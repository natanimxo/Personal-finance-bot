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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                default_account TEXT NOT NULL DEFAULT 'cash'
            )
        """)
    _migrate()


def _migrate():
    """Additive, idempotent migrations. Safe to run on every startup."""
    with get_conn() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(expenses)").fetchall()]
        if "type" not in cols:
            # Existing rows all become 'expense' via the DEFAULT — no data loss,
            # no rows need to be touched manually.
            conn.execute("ALTER TABLE expenses ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'")
        if "account" not in cols:
            # Existing rows default to 'cash' since we have no way to know the real
            # account they belonged to. Users can correct these once transaction
            # editing ships.
            conn.execute("ALTER TABLE expenses ADD COLUMN account TEXT NOT NULL DEFAULT 'cash'")


def register_user(user_id: int):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]


def add_expense(user_id: int, amount: float, category: str, note: str = "", type_: str = "expense", account: str = "cash"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, note, created_at, type, account) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, amount, category.lower(), note, datetime.utcnow().isoformat(), type_, account),
        )


def get_default_account(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT default_account FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["default_account"] if row else "cash"


def set_default_account(user_id: int, account: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, default_account) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET default_account = excluded.default_account",
            (user_id, account),
        )


def account_balances(user_id: int):
    """Returns {account: balance} across all time, income minus expense per account."""
    with get_conn() as conn:
        income_rows = conn.execute(
            "SELECT account, SUM(amount) as total FROM expenses "
            "WHERE user_id = ? AND type = 'income' GROUP BY account",
            (user_id,),
        ).fetchall()
        expense_rows = conn.execute(
            "SELECT account, SUM(amount) as total FROM expenses "
            "WHERE user_id = ? AND type = 'expense' GROUP BY account",
            (user_id,),
        ).fetchall()
        balances = {}
        for r in income_rows:
            balances[r["account"]] = balances.get(r["account"], 0) + r["total"]
        for r in expense_rows:
            balances[r["account"]] = balances.get(r["account"], 0) - r["total"]
        return balances


def get_budget(user_id: int, category: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT amount FROM budgets WHERE user_id = ? AND category = ?",
            (user_id, category.lower()),
        ).fetchone()
        return row["amount"] if row else None


def month_total_for_category(user_id: int, category: str, since: datetime):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(amount) as total FROM expenses "
            "WHERE user_id = ? AND category = ? AND type = 'expense' AND created_at >= ?",
            (user_id, category.lower(), since.isoformat()),
        ).fetchone()
        return row["total"] or 0


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
