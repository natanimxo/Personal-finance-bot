"""Phase 4.4: accounts that fit the user."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_ACCOUNTS, BTN_ADD, BTN_CANCEL
from app.db import init_db
from app.services import accounts, transactions
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()


def test_new_users_start_with_cash_bank_card_mobile_wallet(db):
    assert accounts.choices(UID) == [("cash", "💵 Cash"), ("bank", "🏦 Bank"), ("card", "💳 Card"),
                                     ("mobile_money", "📱 Mobile Wallet")]


def test_the_defaults_can_be_renamed_and_extended(db):
    accounts.rename_account(5, "mobile_money", "📱 Telebirr")
    accounts.add_account(5, "PayPal")
    assert accounts.choices(5) == [("cash", "💵 Cash"), ("bank", "🏦 Bank"), ("card", "💳 Card"),
                                   ("mobile_money", "📱 Telebirr"), ("paypal", "PayPal")]


def test_existing_users_keep_theirs(fresh_db):
    fresh_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(fresh_db)
    conn.executescript("""
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
        CREATE TABLE users (user_id INTEGER PRIMARY KEY);
        INSERT INTO users VALUES (7);
        INSERT INTO expenses (user_id, amount, category, created_at) VALUES (8, 5, 'food', '2026-01-01T00:00:00');
    """)
    conn.close()
    init_db()
    for user in (7, 8):
        assert accounts.choices(user) == [("cash", "💵 Cash"), ("bank", "🏦 Bank"), ("card", "💳 Card"),
                                          ("mobile_money", "📱 Mobile Wallets")]


def test_renamed_account_keeps_history_and_balance(db):
    transactions.add_expense(UID, 30, "food", account="mobile_money")
    accounts.rename_account(UID, "mobile_money", "📲 Safaricom")
    assert accounts.account_balances(UID) == {"mobile_money": -30.0}
    assert transactions.list_recent(UID)[0]["account_name"] == "📲 Safaricom"


def test_add_and_archive(db):
    savings = accounts.add_account(UID, "Savings")
    assert savings["key"] == "savings"
    transactions.add_expense(UID, 10, "food", account="savings")
    accounts.set_default_account(UID, "savings")
    accounts.set_archived(UID, "savings")
    assert "savings" not in dict(accounts.choices(UID))           # gone from pickers
    assert accounts.account_balances(UID)["savings"] == -10.0      # balance stays
    assert accounts.get_default_account(UID) is None               # no longer the default
    with pytest.raises(ValidationError):
        transactions.add_expense(UID, 5, "food", account="savings")
    accounts.set_archived(UID, "savings", False)
    assert "savings" in dict(accounts.choices(UID))


def test_account_rules(db):
    with pytest.raises(ValidationError, match="already"):
        accounts.add_account(UID, "cash")
    with pytest.raises(ValidationError, match="30"):
        accounts.add_account(UID, "x" * 31)
    for key, _ in accounts.choices(UID)[1:]:
        accounts.set_archived(UID, key)
    with pytest.raises(ValidationError, match="at least one"):
        accounts.set_archived(UID, "cash")
    assert accounts.add_account(UID, "Cash 2")["key"] == "cash_2"   # never reuses an original key


def test_entry_on_an_archived_account_can_still_be_edited(db):
    entry_id = transactions.add_expense(UID, 10, "food", account="card")
    accounts.set_archived(UID, "card")
    entry, _ = transactions.update_entry(UID, entry_id, note="still fine")
    assert entry["account"] == "card" and entry["note"] == "still fine"


# --- bot ----------------------------------------------------------------------------
def test_bot_add_rename_archive_restore(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_ACCOUNTS)
            assert "Mobile Wallet" in out.texts[0]
            await h.tap("acc:add")
            out = await h.text("Savings")
            assert "Added" in out.texts[0] and "Savings" in out.texts[-1]

            out = await h.tap("acc:ren")
            assert any(b["callback_data"] == "acc:ren:savings" for b in out.buttons())
            await h.tap("acc:ren:savings")
            out = await h.text("cash")                       # name taken
            assert "already" in out.texts[0]
            out = await h.text("Rainy day")
            assert "Renamed to Rainy day" in out.texts[0]

            await h.tap("acc:arch")
            out = await h.tap("acc:archive:savings")
            assert "Archived Rainy day" in out.texts[-1] and "Archived:" in out.texts[-1]
            await h.tap("acc:restore")
            out = await h.tap("acc:unarch:savings")
            assert "is back" in out.texts[-1]

            await h.text(BTN_ADD)
            await h.text("5")
            out = await h.tap("addcat_food")
            assert "Rainy day" in [b["text"] for b in out.buttons()]

    run(scenario())


def test_bot_cancel_naming(db):
    async def scenario():
        async with Harness() as h:
            await h.tap("acc:add")
            out = await h.text(BTN_CANCEL)
            assert "Cancelled" in out.texts[-1]
            assert len(accounts.choices(UID)) == 4

    run(scenario())


def test_quick_entry_matches_the_users_own_account_names(db):
    accounts.add_account(UID, "Savings")
    accounts.rename_account(UID, "mobile_money", "Telebirr")

    async def scenario():
        async with Harness() as h:
            await h.text("200 food savings")
            await h.text("300 food telebirr")
            got = [(e["amount_minor"], e["account"]) for e in transactions.list_recent(UID)]
            assert got == [(30000, "mobile_money"), (20000, "savings")]

    run(scenario())


# --- API ----------------------------------------------------------------------------
def test_api_accounts(fresh_db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=Harness().app)) as client:
        r = client.post("/api/accounts", headers=headers, json={"name": "Savings"}).json()
        assert [a["account"] for a in r["accounts"]][-1] == "savings"
        r = client.patch("/api/accounts/savings", headers=headers, json={"name": "Goals"}).json()
        assert next(a for a in r["accounts"] if a["account"] == "savings")["label"] == "Goals"
        r = client.patch("/api/accounts/savings", headers=headers, json={"archived": True}).json()
        assert next(a for a in r["accounts"] if a["account"] == "savings")["archived"] is True
        bad = client.post("/api/transactions", headers=headers, json={"amount": 5, "category": "food", "account": "savings"})
        assert bad.status_code == 422 and bad.json()["field"] == "account"
        assert client.post("/api/accounts", headers=headers, json={"name": "cash"}).status_code == 422
        assert client.patch("/api/accounts/nope", headers=headers, json={"name": "X"}).status_code == 422
