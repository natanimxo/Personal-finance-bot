"""Per-user settings: currency and the weekly / monthly recap switches."""
from app import config
from app.db import get_conn
from app.services.validation import check_currency


def get_prefs(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT currency, recap_enabled, monthly_recap_enabled FROM user_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    return {
        "currency": (row["currency"] if row and row["currency"] else config.DEFAULT_CURRENCY),
        "recap_enabled": bool(row["recap_enabled"]) if row else True,
        "monthly_recap_enabled": bool(row["monthly_recap_enabled"]) if row else True,
    }


def set_prefs(user_id: int, currency: str = None, recap_enabled: bool = None,
              monthly_recap_enabled: bool = None) -> dict:
    current = get_prefs(user_id)
    if currency is not None:
        current["currency"] = check_currency(currency)
    if recap_enabled is not None:
        current["recap_enabled"] = bool(recap_enabled)
    if monthly_recap_enabled is not None:
        current["monthly_recap_enabled"] = bool(monthly_recap_enabled)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_prefs (user_id, currency, recap_enabled, monthly_recap_enabled) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET currency = excluded.currency, recap_enabled = excluded.recap_enabled, "
            "monthly_recap_enabled = excluded.monthly_recap_enabled",
            (user_id, current["currency"], int(current["recap_enabled"]), int(current["monthly_recap_enabled"])),
        )
    return current
