"""Each user's own accounts: add, rename, archive, default, balances.

Entries store an account *key*; the name is only for display, so renaming keeps
history and balance. Existing users were given their four original accounts by
migration 005; anyone else starts with Cash, Bank, Card and Mobile Wallet the
first time their accounts are read, and can rename them or add their own.
"""
import re

from app.db import get_conn
from app.services.validation import ValidationError
from app.strings import t

MAX_ACCOUNTS = 12
MAX_NAME = 30
# What a new user starts with, anywhere in the world. The keys are the original
# ones, so quick-entry words (cash, bank, card, wallet, momo...) keep matching.
DEFAULT_ACCOUNTS = [("cash", "💵 Cash"), ("bank", "🏦 Bank"), ("card", "💳 Card"), ("mobile_money", "📱 Mobile Wallet")]


def default_accounts():
    """[(key, name)] for a new user."""
    return list(DEFAULT_ACCOUNTS)


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
        raise ValidationError(t("error.unknown_account"), "account")
    return key


def _check_name(user_id: int, name: str, except_key: str = None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValidationError(t("error.account_name_empty"), "name")
    if len(name) > MAX_NAME:
        raise ValidationError(t("error.account_name_length", max=MAX_NAME), "name")
    for a in list_accounts(user_id, include_archived=True):
        if a["key"] != except_key and _plain(a["name"]) == _plain(name):
            raise ValidationError(t("error.account_name_taken"), "name")
    return name


def _plain(name: str) -> str:
    return re.sub(r"[^\w]+", " ", name.lower()).strip()


def add_account(user_id: int, name: str) -> dict:
    accounts = list_accounts(user_id, include_archived=True)
    if len(accounts) >= MAX_ACCOUNTS:
        raise ValidationError(t("error.account_limit", max=MAX_ACCOUNTS), "name")
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
            raise ValidationError(t("error.unknown_account"), "account")
    return {"key": key, "name": name}


def set_archived(user_id: int, key: str, archived: bool = True):
    """Archive (hide from pickers; history and balance stay) or restore an account."""
    active = list_accounts(user_id)
    if archived and [a["key"] for a in active] == [key]:
        raise ValidationError(t("error.last_account"), "account")
    with get_conn() as conn:
        if not conn.execute("UPDATE accounts SET archived = ? WHERE user_id = ? AND key = ?",
                            (int(archived), user_id, key)).rowcount:
            raise ValidationError(t("error.unknown_account"), "account")
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
    """{account: income - expenses - transfers out + transfers in, in cents}, all time."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT account AS key, SUM(CASE WHEN type = 'income' THEN amount_minor ELSE -amount_minor END) AS total "
            "FROM expenses WHERE user_id = ? GROUP BY account "
            "UNION ALL "
            "SELECT to_account AS key, SUM(amount_minor) AS total "
            "FROM expenses WHERE user_id = ? AND type = 'transfer' GROUP BY to_account",
            (user_id, user_id),
        ).fetchall()
    balances = {}
    for r in rows:
        balances[r["key"]] = balances.get(r["key"], 0) + r["total"]
    return balances


def overview(user_id: int, include_archived: bool = True):
    balances, default = balances_minor(user_id), get_default_account(user_id)
    return [{"account": a["key"], "label": a["name"], "balance_minor": balances.get(a["key"], 0),
             "is_default": a["key"] == default, "archived": a["archived"]}
            for a in list_accounts(user_id, include_archived=include_archived)]


def account_balances(user_id: int):
    """Older float shape, kept for existing callers."""
    return {k: v / 100 for k, v in balances_minor(user_id).items()}
