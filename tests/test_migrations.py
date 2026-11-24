"""Phase 5: start from the very first schema, run every migration, lose nothing."""
import sqlite3

import pytest

from app import db
from app.db import get_conn, init_db
from app.services import accounts, budgets, categories, periods, summaries, transactions

# database.py as first uploaded: no type / account columns, no user_settings.
FIRST_SCHEMA = """
CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
    category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE budgets (user_id INTEGER NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
    PRIMARY KEY (user_id, category));
CREATE TABLE users (user_id INTEGER PRIMARY KEY);
"""
ROWS = [  # (user, amount, category, note, created_at)
    (1, 12.5, "food", "lunch", "2026-07-01T09:15:00.123456"),
    (1, 0.1, "food", None, "2026-07-01T10:00:00"),
    (1, 0.2, "transport", "bus", "2026-07-02T10:00:00"),
    (1, 19.99, "fun", "", "2026-07-03T21:30:00"),
    (2, 100000.0, "bills", "rent 'quoted' & <b>", "2026-07-04T00:00:00"),
]


@pytest.fixture
def old_db(fresh_db):
    fresh_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(fresh_db)
    conn.executescript(FIRST_SCHEMA)
    conn.executemany("INSERT INTO expenses (user_id, amount, category, note, created_at) VALUES (?, ?, ?, ?, ?)", ROWS)
    conn.executemany("INSERT INTO budgets VALUES (?, ?, ?)", [(1, "food", 150.75), (2, "bills", 99999.99)])
    conn.executemany("INSERT INTO users VALUES (?)", [(1,), (2,)])
    conn.commit()
    conn.close()
    return fresh_db


def test_every_migration_runs_in_order_once(old_db):
    init_db()
    with get_conn() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == [v for v, _ in db._migration_files()] == list(range(1, 11))
    assert db.run_migrations() == []


def test_nothing_is_lost(old_db):
    init_db()
    with get_conn() as conn:
        got = conn.execute(
            "SELECT user_id, amount, amount_minor, category, note, created_at, occurred_at, type, account, to_account "
            "FROM expenses ORDER BY id").fetchall()
        assert [tuple(r) for r in got] == [
            (u, a, round(a * 100), c, n, t, t, "expense", "cash", None) for u, a, c, n, t in ROWS]
        assert [tuple(r) for r in conn.execute("SELECT user_id, category, amount, amount_minor FROM budgets ORDER BY user_id")] == [
            (1, "food", 150.75, 15075), (2, "bills", 99999.99, 9999999)]
        assert conn.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0] == 2
    assert db.check_amount_columns()


def test_old_users_keep_their_world(old_db):
    init_db()
    assert accounts.choices(1) == [("cash", "💵 Cash"), ("bank", "🏦 Bank"), ("card", "💳 Card"),
                                   ("mobile_money", "📱 Mobile Wallets")]
    assert accounts.get_default_account(1) is None
    assert [k for k, _ in categories.choices(1, "expense")][:3] == ["food", "transport", "bills"]
    from datetime import datetime, timezone
    s = summaries.summary(1, date_from="2026-07-01", date_to="2026-07-31",
                          now=datetime(2026, 7, 31, tzinfo=timezone.utc))
    assert s["expense_minor"] == 1250 + 10 + 20 + 1999                  # exact cents, no float drift
    assert budgets.get_budget(1, "food") == 150.75
    assert transactions.list_recent(2)[0]["note"] == "rent 'quoted' & <b>"


def test_a_backup_is_taken_before_migrating(old_db):
    init_db()
    copies = list((old_db.parent / "backups").glob("pre-migration-*.db"))
    assert len(copies) == 1
    conn = sqlite3.connect(copies[0])
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == len(ROWS)
    assert "schema_version" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}  # the untouched original
    conn.close()


def test_upgrading_one_phase_at_a_time_gives_the_same_result(old_db, tmp_path, monkeypatch):
    """A database already on Phase 2 (migrations 1-2) upgrades to the same schema as a fresh one."""
    from app import config

    init_db()
    with get_conn() as conn:
        full = sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))

    fresh = tmp_path / "fresh.db"
    monkeypatch.setattr(config, "DB_PATH", str(fresh))
    init_db()
    with get_conn() as conn:
        clean = sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
    norm = lambda rows: sorted(" ".join(r.replace('"', "").split()) for r in rows)  # noqa: E731
    # Same tables, columns and indexes either way (ALTER TABLE spells columns a little differently).
    tables = lambda rows: sorted(r.split("(")[0] for r in norm(rows))  # noqa: E731
    assert tables(full) == tables(clean)
    with get_conn() as conn:
        clean_cols = {t: [c[1] for c in conn.execute(f"PRAGMA table_info({t})")] for t in
                      ("expenses", "budgets", "users", "user_prefs", "accounts", "categories", "recurring")}
    monkeypatch.setattr(config, "DB_PATH", str(old_db))
    with get_conn() as conn:
        old_cols = {t: [c[1] for c in conn.execute(f"PRAGMA table_info({t})")] for t in clean_cols}
    assert {t: sorted(c) for t, c in old_cols.items()} == {t: sorted(c) for t, c in clean_cols.items()}
