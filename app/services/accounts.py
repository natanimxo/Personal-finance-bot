"""Each user's own accounts: add, rename, archive, default, balances.

Entries store an account *key*; the name is only for display, so renaming keeps
history and balance. Existing users were given their four original accounts by
migration 005; anyone else gets DEFAULT_ACCOUNTS (default: Cash, M-Pesa, Bank,
Card) the first time their accounts are read.
"""
import re

from app import config
from app.db import get_conn
from app.services.validation import ValidationError

MAX_ACCOUNTS = 12
MAX_NAME = 30
# Names in DEFAULT_ACCOUNTS that map onto the original keys, so old code paths and
# aliases keep working. The first other name becomes the mobile-money account.
KNOWN = {"cash": ("cash", "💵"), "bank": ("bank", "🏦"), "card": ("card", "💳")}


def default_accounts():
    """[(key, name)] for a new user, from DEFAULT_ACCOUNTS."""
    names = [n.strip() for n in (config.DEFAULT_ACCOUNTS or "").split(",") if n.strip()] or ["Cash", "M-Pesa", "Bank", "Card"]
    result, used = [], set()
    for name in names[:MAX_ACCOUNTS]:
        known = KNOWN.get(name.lower())
        if known and known[0] not in used:
            key, icon = known
        elif "mobile_money" not in used:
            key, icon = "mobile_money", "📱"
        else:
            key, icon = _slug(name, used), "🏷️"
        used.add(key)
        result.append((key, f"{icon} {name}"))
    return result


RESERVED = {"cash", "bank", "card", "mobile_money"}


def _slug(name: str, taken) -> str:
    """A new, unused key for an account name (never one of the original keys)."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "account"
    key, n = base, 2
    while key in taken or key in RESERVED:
        key, n = f"{base}_{n}", n + 1
    return key


def ensure_accounts(user_id: int):
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
            return
        conn.executemany(
            "INSERT OR IGNORE INTO accounts (user_id, key, name, position) VALUES (?, ?, ?, ?)",
            [(user_id, key, name, i) for i, (key, name) in enumerate(default_accounts())],
        )


def list_accounts(user_id: int, include_archived: bool = False):
    ensure_accounts(user_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, name, archived FROM accounts WHERE user_id = ? "
            + ("" if include_archived else "AND archived = 0 ")
            + "ORDER BY archived, position, rowid",
            (user_id,),
        ).fetchall()
    return [{"key": r["key"], "name": r["name"], "archived": bool(r["archived"])} for r in rows]


def choices(user_id: int):
    """[(key, name)] of active accounts, for pickers."""
    return [(a["key"], a["name"]) for a in list_accounts(user_id)]


def names(user_id: int) -> dict:
    """{key: name}, archived included (old entries still show their account)."""
    return {a["key"]: a["name"] for a in list_accounts(user_id, include_archived=True)}


def check_active(user_id: int, key: str) -> str:
    if key not in {a["key"] for a in list_accounts(user_id)}:
        raise ValidationError("Unknown account.", "account")
    return key


def _check_name(user_id: int, name: str, except_key: str = None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValidationError("Give the account a name.", "name")
    if len(name) > MAX_NAME:
        raise ValidationError(f"Account names can be up to {MAX_NAME} characters.", "name")
    for a in list_accounts(user_id, include_archived=True):
        if a["key"] != except_key and _plain(a["name"]) == _plain(name):
            raise ValidationError("You already have an account with that name.", "name")
    return name


def _plain(name: str) -> str:
    return re.sub(r"[^\w]+", " ", name.lower()).strip()


def add_account(user_id: int, name: str) -> dict:
    accounts = list_accounts(user_id, include_archived=True)
    if len(accounts) >= MAX_ACCOUNTS:
        raise ValidationError(f"You can have up to {MAX_ACCOUNTS} accounts.", "name")
    name = _check_name(user_id, name)
    key = _slug(_plain(name), {a["key"] for a in accounts})
    with get_conn() as conn:
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM accounts WHERE user_id = ?",
                                (user_id,)).fetchone()[0]
        conn.execute("INSERT INTO accounts (user_id, key, name, position) VALUES (?, ?, ?, ?)",
                     (user_id, key, name, position))
    return {"key": key, "name": name, "archived": False}


def rename_account(user_id: int, key: str, name: str) -> dict:
    name = _check_name(user_id, name, except_key=key)
    with get_conn() as conn:
        if not conn.execute("UPDATE accounts SET name = ? WHERE user_id = ? AND key = ?", (name, user_id, key)).rowcount:
            raise ValidationError("Unknown account.", "account")
    return {"key": key, "name": name}


def set_archived(user_id: int, key: str, archived: bool = True):
    """Archive (hide from pickers; history and balance stay) or restore an account."""
    active = list_accounts(user_id)
    if archived and [a["key"] for a in active] == [key]:
        raise ValidationError("You need at least one account that isn't archived.", "account")
    with get_conn() as conn:
        if not conn.execute("UPDATE accounts SET archived = ? WHERE user_id = ? AND key = ?",
                            (int(archived), user_id, key)).rowcount:
            raise ValidationError("Unknown account.", "account")
        if archived:
            conn.execute("DELETE FROM user_settings WHERE user_id = ? AND default_account = ?", (user_id, key))


def get_default_account(user_id: int):
    """The account the user picked as default, or None if they never picked one."""
    with get_conn() as conn:
        row = conn.execute("SELECT default_account FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return row["default_account"] if row else None


def fallback_account(user_id: int) -> str:
    """The account to use when none was chosen: the default, else the first active one."""
    return get_default_account(user_id) or choices(user_id)[0][0]


def set_default_account(user_id: int, account: str):
    check_active(user_id, account)
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


def overview(user_id: int, include_archived: bool = True):
    balances, default = balances_minor(user_id), get_default_account(user_id)
    return [{"account": a["key"], "label": a["name"], "balance_minor": balances.get(a["key"], 0),
             "is_default": a["key"] == default, "archived": a["archived"]}
            for a in list_accounts(user_id, include_archived=include_archived)]


def account_balances(user_id: int):
    """Older float shape, kept for existing callers."""
    return {k: v / 100 for k, v in balances_minor(user_id).items()}
