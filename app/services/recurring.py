"""Recurring entries: weekly or monthly income/expenses created automatically.

A rule is made from an existing entry ("repeat this weekly / monthly"); the next
copy is due one period after that entry's date. Every day at 06:00
(APP_TIMEZONE) process_due() creates what is due. Each rule's next_date is
advanced in the same transaction as the insert, and only if it still has the
value that was read, so running the job twice (or restarting halfway) never
creates a duplicate.
"""
import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from app.db import get_conn
from app.services import catalog, periods, transactions
from app.services.validation import ValidationError

logger = logging.getLogger(__name__)

FREQUENCIES = ("weekly", "monthly")
MAX_CATCH_UP = 12   # at most this many missed copies per rule in one run
MAX_RULES = 30


def advance(day: date, frequency: str, anchor_day: int) -> date:
    if frequency == "weekly":
        return day + timedelta(days=7)
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def _rule(row):
    rule = dict(row)
    from app.services.categories import label
    rule["category_label"] = label(rule["user_id"], rule["type"], rule["category"])
    return rule


def create_from_entry(user_id: int, entry_id: int, frequency: str) -> dict:
    if frequency not in FREQUENCIES:
        raise ValidationError("Repeat weekly or monthly.", "frequency")
    entry = transactions.get_entry(user_id, entry_id)
    if entry is None:
        raise ValidationError("No such entry.", "entry")
    if entry["type"] not in ("expense", "income"):
        raise ValidationError("Only income and expenses can repeat.", "entry")
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM recurring WHERE user_id = ?", (user_id,)).fetchone()[0] >= MAX_RULES:
            raise ValidationError(f"You can have up to {MAX_RULES} recurring entries.", "frequency")
    first = periods.local_date_of(entry["occurred_at"])
    anchor = first.weekday() if frequency == "weekly" else first.day
    next_date = advance(first, frequency, anchor)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recurring (user_id, type, amount_minor, category, account, note, frequency, anchor_day, "
            "next_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, entry["type"], entry["amount_minor"], entry["category"], entry["account"], entry["note"] or "",
             frequency, anchor, next_date.isoformat(), datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
        )
        rule_id = cur.lastrowid
    return get_rule(user_id, rule_id)


def get_rule(user_id: int, rule_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM recurring WHERE id = ? AND user_id = ?", (rule_id, user_id)).fetchone()
    return _rule(row) if row else None


def list_rules(user_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM recurring WHERE user_id = ? ORDER BY next_date, id", (user_id,)).fetchall()
    return [_rule(r) for r in rows]


def delete_rule(user_id: int, rule_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute("DELETE FROM recurring WHERE id = ? AND user_id = ?", (rule_id, user_id)).rowcount > 0


def process_due(today: date = None):
    """Create every entry that is due up to `today`. Returns [(rule, entry_id)] created."""
    today = today or periods.today()
    created = []
    with get_conn() as conn:
        due = conn.execute("SELECT * FROM recurring WHERE next_date <= ? ORDER BY id", (today.isoformat(),)).fetchall()
    for row in due:
        rule = dict(row)
        for _ in range(MAX_CATCH_UP):
            day = date.fromisoformat(rule["next_date"])
            if day > today:
                break
            following = advance(day, rule["frequency"], rule["anchor_day"]).isoformat()
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            with get_conn() as conn:
                claimed = conn.execute(
                    "UPDATE recurring SET next_date = ? WHERE id = ? AND next_date = ?",
                    (following, rule["id"], rule["next_date"]),
                ).rowcount
                if not claimed:  # another run already handled this date
                    break
                cur = conn.execute(
                    "INSERT INTO expenses (user_id, amount, amount_minor, category, note, created_at, occurred_at, "
                    "type, account) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rule["user_id"], rule["amount_minor"] / 100, rule["amount_minor"], rule["category"], rule["note"],
                     now, periods.occurred_at_for(day), rule["type"], rule["account"]),
                )
                created.append((_rule(rule), cur.lastrowid))
            rule["next_date"] = following
    if created:
        logger.info("Recurring entries created: %d", len(created))
    return created
