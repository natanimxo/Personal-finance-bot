"""Income and expense entries. All business rules for entries live here, so the
bot and the Mini App can never disagree. Amounts are integer cents (amount_minor)."""
from datetime import date, datetime, timedelta, timezone

from app.db import get_conn
from app.services import budgets, periods, validation

COLUMNS = "id, user_id, amount_minor, category, note, created_at, occurred_at, type, account"
PAGE_SIZE = 30


def _entry(row):
    if row is None:
        return None
    entry = dict(row)
    entry["amount"] = entry["amount_minor"] / 100  # convenience for display code
    return entry


def _now_db() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def get_entry(user_id: int, entry_id: int):
    with get_conn() as conn:
        return _entry(conn.execute(
            f"SELECT {COLUMNS} FROM expenses WHERE id = ? AND user_id = ?", (entry_id, user_id)
        ).fetchone())


def _warning(user_id: int, entry):
    """A budget warning, only for an expense that falls in the current month."""
    if entry["type"] != "expense":
        return None
    if periods.local_date_of(entry["occurred_at"]) < periods.month_start().date():
        return None
    return budgets.warning_for(user_id, entry["category"])


def add_entry(user_id: int, amount_minor: int, type_: str, category: str, account: str, note: str = "",
              day=None):
    """Validate and save an entry. `day` is the local date it happened (default today).
    Returns (entry, budget_warning or None)."""
    day = validation.check_date(day)
    validation.check_type(type_)
    validation.check_category(category, type_)
    validation.check_account(account)
    note = validation.check_note(note)
    if not isinstance(amount_minor, int) or amount_minor <= 0 or amount_minor > validation.MAX_AMOUNT * 100:
        raise validation.ValidationError("Invalid amount.", "amount")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, amount_minor, category, note, created_at, occurred_at, type, account) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, amount_minor / 100, amount_minor, category, note, _now_db(), periods.occurred_at_for(day),
             type_, account),
        )
        entry_id = cur.lastrowid
    entry = get_entry(user_id, entry_id)
    return entry, _warning(user_id, entry)


def update_entry(user_id: int, entry_id: int, **changes):
    """Change any of amount_minor, type, category, account, note, day (a local date).
    Returns (entry, budget_warning) or (None, None) if the entry isn't the user's."""
    current = get_entry(user_id, entry_id)
    if current is None:
        return None, None
    day = changes.pop("day", None)
    occurred_at = current["occurred_at"]
    if day not in (None, ""):
        day = validation.check_date(day)
        if day != periods.local_date_of(occurred_at):
            occurred_at = periods.occurred_at_for(day)
    merged = {k: current[k] for k in ("amount_minor", "type", "category", "account", "note")}
    merged.update({k: v for k, v in changes.items() if v is not None})
    validation.check_type(merged["type"])
    validation.check_category(merged["category"], merged["type"])
    validation.check_account(merged["account"])
    merged["note"] = validation.check_note(merged["note"])
    amount_minor = merged["amount_minor"]
    if not isinstance(amount_minor, int) or amount_minor <= 0 or amount_minor > validation.MAX_AMOUNT * 100:
        raise validation.ValidationError("Invalid amount.", "amount")
    with get_conn() as conn:
        conn.execute(
            "UPDATE expenses SET amount = ?, amount_minor = ?, type = ?, category = ?, account = ?, note = ?, "
            "occurred_at = ? WHERE id = ? AND user_id = ?",
            (amount_minor / 100, amount_minor, merged["type"], merged["category"], merged["account"],
             merged["note"], occurred_at, entry_id, user_id),
        )
    entry = get_entry(user_id, entry_id)
    return entry, _warning(user_id, entry)


def delete_entry(user_id: int, entry_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (entry_id, user_id)).rowcount > 0


def _day_start(day: str) -> str:
    """YYYY-MM-DD (local) -> its local midnight in stored form."""
    d = date.fromisoformat(day)
    return periods.to_db(datetime(d.year, d.month, d.day, tzinfo=periods.tz()))


def make_cursor(entry) -> str:
    return f"{entry['occurred_at']}~{entry['id']}"


def parse_cursor(cursor: str):
    try:
        occurred_at, entry_id = str(cursor).rsplit("~", 1)
        datetime.fromisoformat(occurred_at)
        return occurred_at, int(entry_id)
    except ValueError:
        raise validation.ValidationError("Invalid cursor.", "cursor")


def list_entries(user_id: int, cursor: str = None, type_: str = None, category: str = None, account: str = None,
                 date_from: str = None, date_to: str = None, q: str = None, limit: int = PAGE_SIZE):
    """Newest first (by the date it happened, then id). Returns (entries, next_cursor); next_cursor
    is None on the last page. date_from / date_to are local dates, both inclusive."""
    where, args = ["user_id = ?"], [user_id]
    if cursor:
        occurred_at, entry_id = parse_cursor(cursor)
        where.append("(occurred_at < ? OR (occurred_at = ? AND id < ?))"); args += [occurred_at, occurred_at, entry_id]
    if type_:
        where.append("type = ?"); args.append(validation.check_type(type_))
    if category:
        where.append("category = ?"); args.append(category)
    if account:
        where.append("account = ?"); args.append(account)
    if date_from:
        where.append("occurred_at >= ?"); args.append(_day_start(date_from))
    if date_to:
        next_day = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
        where.append("occurred_at < ?"); args.append(_day_start(next_day))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("note LIKE ? ESCAPE '\\'"); args.append(f"%{escaped}%")
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {COLUMNS} FROM expenses WHERE {' AND '.join(where)} ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
    entries = [_entry(r) for r in rows[:limit]]
    next_cursor = make_cursor(entries[-1]) if len(rows) > limit else None
    return entries, next_cursor


# ---------------------------------------------------------------------------
# Older call shapes, kept for the bot's existing code paths and tests.
# ---------------------------------------------------------------------------
def add_expense(user_id: int, amount: float, category: str, note: str = "", type_: str = "expense", account: str = "cash") -> int:
    entry, _ = add_entry(user_id, validation.to_minor(amount), type_, category.lower(), account, note)
    return entry["id"]


def set_account(user_id: int, expense_id: int, account: str) -> bool:
    entry, _ = update_entry(user_id, expense_id, account=account)
    return entry is not None


def delete_expense(user_id: int, expense_id: int) -> bool:
    return delete_entry(user_id, expense_id)


def list_recent(user_id: int, limit: int = 10, type_: str = None):
    return list_entries(user_id, type_=type_, limit=limit)[0]
