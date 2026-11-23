from app.db import get_conn
from app.services import catalog


def get_default_account(user_id: int):
    """The account the user picked as default, or None if they never picked one."""
    with get_conn() as conn:
        row = conn.execute("SELECT default_account FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return row["default_account"] if row else None


def set_default_account(user_id: int, account: str):
    from app.services.validation import check_account
    check_account(account)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, default_account) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET default_account = excluded.default_account",
            (user_id, account),
        )


def balances_minor(user_id: int) -> dict:
    """{account: income minus expenses, in cents}, all time."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT account, SUM(CASE WHEN type = 'income' THEN amount_minor ELSE -amount_minor END) AS total "
            "FROM expenses WHERE user_id = ? GROUP BY account",
            (user_id,),
        ).fetchall()
    return {r["account"]: r["total"] for r in rows}


def overview(user_id: int):
    balances, default = balances_minor(user_id), get_default_account(user_id)
    return [{"account": key, "label": label, "balance_minor": balances.get(key, 0), "is_default": key == default}
            for key, label in catalog.ACCOUNTS]


def account_balances(user_id: int):
    """Older float shape, kept for existing callers."""
    return {k: v / 100 for k, v in balances_minor(user_id).items()}
