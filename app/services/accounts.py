from app.db import get_conn


def get_default_account(user_id: int):
    """The account the user picked as default, or None if they never picked one."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT default_account FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["default_account"] if row else None


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
