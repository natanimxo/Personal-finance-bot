"""Phase 5: bringing rescued data onto a new volume with /restore."""
import gzip
import os
import sqlite3

import pytest

from app import config
from app.bot.keyboards import BTN_HISTORY
from app.db import get_conn, init_db
from app.services import accounts, transactions
from tests.fake_telegram import UID, Harness, run

# The database as the original bot.py / database.py left it on Railway.
LIVE_SCHEMA = """
CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
    category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'expense',
    account TEXT NOT NULL DEFAULT 'cash');
CREATE TABLE budgets (user_id INTEGER NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
    PRIMARY KEY (user_id, category));
CREATE TABLE users (user_id INTEGER PRIMARY KEY);
CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, default_account TEXT NOT NULL DEFAULT 'cash');
INSERT INTO users VALUES (42), (77);
INSERT INTO expenses (user_id, amount, category, note, created_at, type, account) VALUES
    (42, 1200.5, 'food', 'groceries', '2026-11-02T08:00:00', 'expense', 'mobile_money'),
    (42, 45000, 'salary', '', '2026-11-01T06:00:00', 'income', 'bank'),
    (77, 80, 'transport', 'bus', '2026-11-03T07:00:00', 'expense', 'cash');
INSERT INTO budgets VALUES (42, 'food', 3000);
INSERT INTO user_settings VALUES (42, 'mobile_money');
"""


@pytest.fixture
def rescued(tmp_path):
    path = tmp_path / "finance_bot.db"
    conn = sqlite3.connect(path)
    conn.executescript(LIVE_SCHEMA)
    conn.close()
    return path.read_bytes()


@pytest.fixture
def fresh_volume(fresh_db, monkeypatch):
    init_db()                                   # a new, empty database on the new volume
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
    return fresh_db


def test_admin_restores_the_rescued_file(fresh_volume, rescued):
    async def scenario():
        async with Harness() as h:
            out = await h.document(rescued, "finance_bot.db", "/restore")
            assert "Restored: 3 entries, 2 users, 1 budgets" in out.texts[-1]
            assert "Migrations applied: 14" in out.texts[-1]

            # Everything is there, upgraded: exact cents, dates, accounts, default.
            e = transactions.list_recent(UID)
            assert [(x["amount_minor"], x["category"], x["account"]) for x in e] == [
                (120050, "food", "mobile_money"), (4500000, "salary", "bank")]
            assert e[0]["occurred_at"] == "2026-11-02T08:00:00"
            assert accounts.get_default_account(UID) == "mobile_money"
            assert accounts.choices(UID)[-1] == ("mobile_money", "📱 Mobile Wallets")   # they keep their 4
            # The old database had no currency or timezone: existing users are asked once.
            out = await h.text(BTN_HISTORY)
            assert "Which currency" in out.texts[0]
            await h.tap("ob:cur:KES")
            await h.text("Nairobi")
            out = await h.text(BTN_HISTORY)
            assert "groceries" in out.texts[0] and "KES" in out.texts[0]

    run(scenario())
    backups = os.listdir(fresh_volume.parent / "backups")
    assert any(b.startswith("pre-restore-") for b in backups)       # the empty db was saved first


def test_gzipped_backup_from_the_admin_chat_works_too(fresh_volume, rescued):
    async def scenario():
        async with Harness() as h:
            out = await h.document(gzip.compress(rescued), "expenses-2026-11-23.db.gz", "/restore")
            assert "Restored: 3 entries" in out.texts[-1]

    run(scenario())


def test_bad_file_changes_nothing(fresh_volume):
    transactions.add_expense(UID, 5, "food", "keep me")

    async def scenario():
        async with Harness() as h:
            out = await h.document(b"definitely not a database", "notes.db", "/restore")
            assert "Not restored" in out.texts[-1] and "Nothing was changed" in out.texts[-1]
            assert transactions.list_recent(UID)[0]["note"] == "keep me"

    run(scenario())


def test_only_the_admin_with_the_caption(fresh_volume, rescued, monkeypatch):
    async def scenario():
        async with Harness() as h:
            assert await h.document(rescued, "finance_bot.db", "here you go") == []      # no /restore caption
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)
            assert await h.document(rescued, "finance_bot.db", "/restore") == []         # not the admin
            with get_conn() as conn:
                assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0

    run(scenario())
