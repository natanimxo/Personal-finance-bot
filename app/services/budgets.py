"""Monthly budgets per expense category, and the 80% / 100% warnings."""
from datetime import datetime

from app.db import get_conn
from app.services import catalog, periods
from app.services.periods import to_db

WARN_AT = 80  # percent


def get_limit_minor(user_id: int, category: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT amount_minor FROM budgets WHERE user_id = ? AND category = ?", (user_id, category)
        ).fetchone()
        return row["amount_minor"] if row else None


def set_limit(user_id: int, category: str, limit_minor):
    """Set a monthly limit in cents, or remove it with None / 0."""
    with get_conn() as conn:
        if not limit_minor:
            conn.execute("DELETE FROM budgets WHERE user_id = ? AND category = ?", (user_id, category))
            return
        conn.execute(
            "INSERT INTO budgets (user_id, category, amount, amount_minor) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, category) DO UPDATE SET amount = excluded.amount, amount_minor = excluded.amount_minor",
            (user_id, category, limit_minor / 100, limit_minor),
        )


def spent_minor(user_id: int, category: str, since: datetime) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(amount_minor) AS total FROM expenses "
            "WHERE user_id = ? AND category = ? AND type = 'expense' AND occurred_at >= ?",
            (user_id, category, to_db(since)),
        ).fetchone()
        return row["total"] or 0


def warning_for(user_id: int, category: str, now: datetime = None):
    """{"level": "near"|"over", ...} when this month's spending is at 80% or more of the limit."""
    limit = get_limit_minor(user_id, category)
    if not limit:
        return None
    spent = spent_minor(user_id, category, periods.month_start(now))
    pct = spent / limit * 100
    if spent > limit:
        level = "over"
    elif pct >= WARN_AT:
        level = "near"
    else:
        return None
    return {"level": level, "category": category, "label": catalog.label_for(category, "expense"),
            "spent_minor": spent, "limit_minor": limit, "percent": round(pct)}


def overview(user_id: int, now: datetime = None):
    """Every expense category with its limit (or None) and this month's spending."""
    since = periods.month_start(now)
    with get_conn() as conn:
        limits = {r["category"]: r["amount_minor"] for r in conn.execute(
            "SELECT category, amount_minor FROM budgets WHERE user_id = ?", (user_id,))}
        spent = {r["category"]: r["total"] for r in conn.execute(
            "SELECT category, SUM(amount_minor) AS total FROM expenses "
            "WHERE user_id = ? AND type = 'expense' AND occurred_at >= ? GROUP BY category",
            (user_id, to_db(since)))}
    items = []
    for key, label in catalog.CATEGORIES:
        limit, used = limits.get(key), spent.get(key, 0) or 0
        items.append({"category": key, "label": label, "limit_minor": limit, "spent_minor": used,
                      "percent": round(used / limit * 100) if limit else None})
    return items


# Older call shapes (floats), kept for existing bot code and tests.
def get_budget(user_id: int, category: str):
    limit = get_limit_minor(user_id, category.lower())
    return limit / 100 if limit else None


def set_budget(user_id: int, category: str, amount: float):
    from app.services.validation import to_minor
    set_limit(user_id, category.lower(), to_minor(amount))


def get_budgets(user_id: int):
    with get_conn() as conn:
        return [{"category": r["category"], "amount": r["amount_minor"] / 100} for r in conn.execute(
            "SELECT category, amount_minor FROM budgets WHERE user_id = ?", (user_id,))]


def month_total_for_category(user_id: int, category: str, since: datetime):
    return spent_minor(user_id, category.lower(), since) / 100
