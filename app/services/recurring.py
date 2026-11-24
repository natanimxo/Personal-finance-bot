"""Recurring entries: weekly or monthly income/expenses created automatically.

A rule is made from an existing entry ("repeat this weekly / monthly"); the next
copy is due one period after that entry's date. An hourly job runs
process_due(), which creates a copy once it is at least 06:00 on its date in the
user's own timezone. Each rule's next_date is
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
from app.strings import t

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


@periods.in_user_zone
def create_from_entry(user_id: int, entry_id: int, frequency: str) -> dict:
    if frequency not in FREQUENCIES:
        raise ValidationError(t("error.repeat"), "frequency")
    entry = transactions.get_entry(user_id, entry_id)
    if entry is None:
        raise ValidationError(t("error.no_entry"), "entry")
    if entry["type"] not in ("expense", "income"):
        raise ValidationError(t("error.repeat_type"), "entry")
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM recurring WHERE user_id = ?", (user_id,)).fetchone()[0] >= MAX_RULES:
            raise ValidationError(t("error.rule_limit", max=MAX_RULES), "frequency")
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


RUN_FROM_HOUR = 6  # a copy is made from 06:00 on its date, the user's time


def _due_until(user_id: int, now: datetime = None) -> date:
    """The last date whose copies are due for this user now: today once it's 06:00
    in their timezone, else yesterday."""
    with periods.for_user(user_id):
        local = periods.now_local(now)
    return local.date() if local.hour >= RUN_FROM_HOUR else local.date() - timedelta(days=1)


def process_due(today: date = None, now: datetime = None):
    """Create every entry that is due. With `today`, everything up to that date (any
    user); otherwise up to each user's own today (from 06:00 their time).
    Returns [(rule, entry_id)] created."""
    # No user's local date is ever more than a day past UTC's, so this finds every candidate.
    latest = today or (datetime.now(timezone.utc) if now is None else now).date() + timedelta(days=1)
    created = []
    with get_conn() as conn:
        due = conn.execute("SELECT * FROM recurring WHERE next_date <= ? ORDER BY id", (latest.isoformat(),)).fetchall()
    until = {}
    for row in due:
        rule = dict(row)
        if rule["user_id"] not in until:
            until[rule["user_id"]] = today or _due_until(rule["user_id"], now)
        created += _create_rule_copies(rule["user_id"], rule, until[rule["user_id"]])
    if created:
        logger.info("Recurring entries created: %d", len(created))
    return created


@periods.in_user_zone
def _create_rule_copies(user_id: int, rule: dict, today: date):
    """Copies of one rule up to `today`, each dated its own day (in the user's zone)."""
    created = []
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
    return created
