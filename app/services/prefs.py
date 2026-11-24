"""Per-user settings: currency, timezone and the weekly / monthly recap switches.

There is no app-wide currency or timezone. Both are None until the user picks
them (the bot asks on /start); until then amounts show without a currency code
and dates use UTC.
"""
from app.db import get_conn
from app.services.validation import check_currency, check_timezone

_UNSET = object()


def get_prefs(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT currency, timezone, recap_enabled, monthly_recap_enabled FROM user_prefs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    currency = row["currency"] if row and row["currency"] else None
    zone = row["timezone"] if row and row["timezone"] else None
    return {
        "currency": currency,
        "timezone": zone,
        "recap_enabled": bool(row["recap_enabled"]) if row else True,
        "monthly_recap_enabled": bool(row["monthly_recap_enabled"]) if row else True,
        "onboarded": bool(currency and zone),
    }


def is_onboarded(user_id: int) -> bool:
    return get_prefs(user_id)["onboarded"]


def currency_of(user_id: int):
    return get_prefs(user_id)["currency"]


def set_prefs(user_id: int, currency: str = None, recap_enabled: bool = None,
              monthly_recap_enabled: bool = None, timezone: str = None) -> dict:
    current = get_prefs(user_id)
    if currency is not None:
        current["currency"] = check_currency(currency)
    if timezone is not None:
        current["timezone"] = check_timezone(timezone)
    if recap_enabled is not None:
        current["recap_enabled"] = bool(recap_enabled)
    if monthly_recap_enabled is not None:
        current["monthly_recap_enabled"] = bool(monthly_recap_enabled)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_prefs (user_id, currency, timezone, recap_enabled, monthly_recap_enabled) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET currency = excluded.currency, timezone = excluded.timezone, "
            "recap_enabled = excluded.recap_enabled, monthly_recap_enabled = excluded.monthly_recap_enabled",
            (user_id, current["currency"], current["timezone"], int(current["recap_enabled"]),
             int(current["monthly_recap_enabled"])),
        )
    if timezone is not None:
        from app.services import periods
        if periods._zone.get()[0] == user_id:  # the rest of this update uses the new zone
            periods.set_zone(current["timezone"], user_id)
    current["onboarded"] = bool(current["currency"] and current["timezone"])
    return current
