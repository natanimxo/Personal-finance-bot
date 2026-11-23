"""Phase 4.5: transfers between accounts."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_CANCEL, BTN_HISTORY
from app.db import init_db
from app.services import accounts, budgets, periods, summaries, transactions
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()
    transactions.add_expense(UID, 1000, "salary", type_="income", account="mobile_money")


def test_transfer_moves_money_but_leaves_the_summary_alone(db):
    before = summaries.summary(UID, "month")
    entry = transactions.add_transfer(UID, 30000, "mobile_money", "cash", "withdrawal")
    after = summaries.summary(UID, "month")
    for key in ("income_minor", "expense_minor", "net_minor", "savings_rate", "by_category"):
        assert before[key] == after[key], key
    assert accounts.balances_minor(UID) == {"mobile_money": 70000, "cash": 30000}
    assert entry["type"] == "transfer" and entry["to_account_name"] == "💵 Cash"


def test_transfer_does_not_touch_budgets(db):
    budgets.set_budget(UID, "food", 10)
    transactions.add_transfer(UID, 5000, "mobile_money", "cash")
    assert budgets.month_total_for_category(UID, "food", periods.month_start()) == 0


def test_transfer_rules(db):
    with pytest.raises(ValidationError, match="different"):
        transactions.add_transfer(UID, 100, "cash", "cash")
    with pytest.raises(ValidationError):
        transactions.add_transfer(UID, 100, "cash", "nope")
    entry = transactions.add_transfer(UID, 100, "cash", "bank")
    with pytest.raises(ValidationError):
        transactions.update_entry(UID, entry["id"], type="expense", category="food")
    with pytest.raises(ValidationError, match="different"):
        transactions.update_entry(UID, entry["id"], to_account="cash")
    edited, warning = transactions.update_entry(UID, entry["id"], amount_minor=250, to_account="card")
    assert (edited["amount_minor"], edited["to_account"], warning) == (250, "card", None)
    assert accounts.balances_minor(UID)["card"] == 250 and accounts.balances_minor(UID).get("bank", 0) == 0


def test_deleting_a_transfer_restores_both_balances(db):
    entry = transactions.add_transfer(UID, 30000, "mobile_money", "cash")
    transactions.delete_entry(UID, entry["id"])
    assert accounts.balances_minor(UID) == {"mobile_money": 100000}


def test_history_filter_and_account_filter_see_transfers(db):
    transactions.add_transfer(UID, 500, "mobile_money", "cash")
    assert [e["type"] for e in transactions.list_entries(UID, type_="transfer")[0]] == ["transfer"]
    assert len(transactions.list_entries(UID, account="cash")[0]) == 1      # matched as the "to" side


# --- bot ----------------------------------------------------------------------------
def test_bot_transfer_flow(db):
    async def scenario():
        async with Harness() as h:
            out = await h.tap("acc:transfer")
            assert any(b["callback_data"] == "trf:mobile_money" for b in out.buttons())
            out = await h.tap("trf:mobile_money")
            assert "trt:mobile_money" not in [b["callback_data"] for b in out.buttons()]
            await h.tap("trt:cash")
            out = await h.text("12.345")
            assert "2 decimal" in out.texts[0]
            out = await h.text("300")
            assert "🔁 Moved KES 300 — 📱 M-Pesa → 💵 Cash" in out.texts[-1]
            assert any(b["callback_data"].startswith("undo:") for b in out.buttons())
            assert accounts.balances_minor(UID) == {"mobile_money": 70000, "cash": 30000}
            out = await h.text(BTN_HISTORY)
            assert "🔁 KES 300 📱 M-Pesa → 💵 Cash" in out.texts[0]

    run(scenario())


def test_bot_transfer_cancel_and_edit(db):
    entry = transactions.add_transfer(UID, 500, "mobile_money", "cash")

    async def scenario():
        async with Harness() as h:
            await h.tap("acc:transfer")
            out = await h.tap("flow_cancel")
            assert "Cancelled" in out.texts[-1]

            out = await h.tap(f"edit:{entry['id']}")
            labels = [b["text"] for b in out.buttons()]
            assert "➡️ To" in labels and "⬅️ From" in labels and "🏷️ Category" not in labels
            await h.tap(f"edto:{entry['id']}")
            await h.tap(f"edsetto:{entry['id']}:bank")
            assert transactions.get_entry(UID, entry["id"])["to_account"] == "bank"

    run(scenario())


# --- API ----------------------------------------------------------------------------
def test_api_transfers(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=Harness().app)) as client:
        r = client.post("/api/transfers", headers=headers,
                        json={"amount": "250", "from_account": "mobile_money", "to_account": "bank"})
        assert r.status_code == 201
        e = r.json()["entry"]
        assert (e["type"], e["account"], e["to_account"], e["category_label"]) == ("transfer", "mobile_money", "bank", "🔁 Transfer")
        s = client.get("/api/summary?period=month", headers=headers).json()
        assert s["expense_minor"] == 0 and s["income_minor"] == 100000
        balances = {a["account"]: a["balance_minor"] for a in s["accounts"]}
        assert balances["bank"] == 25000 and balances["mobile_money"] == 75000
        r = client.patch(f"/api/transactions/{e['id']}", headers=headers, json={"to_account": "card"})
        assert r.json()["entry"]["to_account"] == "card"
        bad = client.post("/api/transfers", headers=headers, json={"amount": 5, "from_account": "cash", "to_account": "cash"})
        assert bad.status_code == 422
        assert client.get("/api/transactions?type=transfer", headers=headers).json()["items"][0]["id"] == e["id"]
