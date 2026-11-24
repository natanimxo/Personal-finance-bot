"""Each user's own categories, for expenses and for income: add, rename, hide.

Entries store a category *key*; the name is only for display, so a rename keeps
history. Hiding takes a category out of the pickers, while its past entries
still count in summaries and budgets. Everyone starts from the built-in list.
"""
import re

from app.db import get_conn
from app.services import catalog
from app.services.validation import ValidationError, check_type

MAX_PER_TYPE = 20
MAX_NAME = 30


def ensure_categories(user_id: int, type_: str):
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM categories WHERE user_id = ? AND type = ? LIMIT 1", (user_id, type_)).fetchone():
            return
        conn.executemany(
            "INSERT OR IGNORE INTO categories (user_id, type, key, name, position) VALUES (?, ?, ?, ?, ?)",
            [(user_id, type_, key, name, i) for i, (key, name) in enumerate(catalog.categories_for(type_))],
        )


def list_categories(user_id: int, type_: str, include_hidden: bool = False):
    check_type(type_)
    ensure_categories(user_id, type_)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, name, hidden FROM categories WHERE user_id = ? AND type = ? "
            + ("" if include_hidden else "AND hidden = 0 ")
            + "ORDER BY hidden, position, rowid",
            (user_id, type_),
        ).fetchall()
    return [{"key": r["key"], "name": r["name"], "hidden": bool(r["hidden"])} for r in rows]


def choices(user_id: int, type_: str):
    """[(key, name)] of visible categories, for pickers."""
    return [(c["key"], c["name"]) for c in list_categories(user_id, type_)]


def names(user_id: int, type_: str) -> dict:
    """{key: name}, hidden included (old entries still show their category)."""
    return {c["key"]: c["name"] for c in list_categories(user_id, type_, include_hidden=True)}


def label(user_id: int, type_: str, key: str) -> str:
    return names(user_id, type_).get(key) or catalog.label_for(key, type_)


def check_active(user_id: int, type_: str, key: str) -> str:
    if key not in {c["key"] for c in list_categories(user_id, type_)}:
        raise ValidationError(f"Unknown {type_} category.", "category")
    return key


def _plain(name: str) -> str:
    return re.sub(r"[^\w]+", " ", name.lower()).strip()


def _check_name(user_id: int, type_: str, name: str, except_key: str = None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValidationError("Give the category a name.", "name")
    if len(name) > MAX_NAME:
        raise ValidationError(f"Category names can be up to {MAX_NAME} characters.", "name")
    for c in list_categories(user_id, type_, include_hidden=True):
        if c["key"] != except_key and _plain(c["name"]) == _plain(name):
            raise ValidationError("You already have a category with that name.", "name")
    return name


def add_category(user_id: int, type_: str, name: str) -> dict:
    existing = list_categories(user_id, type_, include_hidden=True)
    if len(existing) >= MAX_PER_TYPE:
        raise ValidationError(f"You can have up to {MAX_PER_TYPE} {type_} categories.", "name")
    name = _check_name(user_id, type_, name)
    base = re.sub(r"[^a-z0-9]+", "_", _plain(name)).strip("_")[:20] or "category"
    taken = {c["key"] for c in existing} | {k for k, _ in catalog.categories_for(type_)} | {"transfer"}
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    with get_conn() as conn:
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories WHERE user_id = ? AND type = ?",
                                (user_id, type_)).fetchone()[0]
        conn.execute("INSERT INTO categories (user_id, type, key, name, position) VALUES (?, ?, ?, ?, ?)",
                     (user_id, type_, key, name, position))
    return {"key": key, "name": name, "hidden": False}


def rename_category(user_id: int, type_: str, key: str, name: str) -> dict:
    name = _check_name(user_id, type_, name, except_key=key)
    with get_conn() as conn:
        if not conn.execute("UPDATE categories SET name = ? WHERE user_id = ? AND type = ? AND key = ?",
                            (name, user_id, type_, key)).rowcount:
            raise ValidationError("Unknown category.", "category")
    return {"key": key, "name": name}


def set_hidden(user_id: int, type_: str, key: str, hidden: bool = True):
    visible = list_categories(user_id, type_)
    if hidden and [c["key"] for c in visible] == [key]:
        raise ValidationError("Keep at least one category visible.", "category")
    with get_conn() as conn:
        if not conn.execute("UPDATE categories SET hidden = ? WHERE user_id = ? AND type = ? AND key = ?",
                            (int(hidden), user_id, type_, key)).rowcount:
            raise ValidationError("Unknown category.", "category")


def as_json(user_id: int) -> dict:
    """{"expense": [{key, label, hidden}], "income": [...]}, hidden included (the app filters)."""
    return {t: [{"key": c["key"], "label": c["name"], "hidden": c["hidden"]}
                for c in list_categories(user_id, t, include_hidden=True)] for t in catalog.TYPES}
