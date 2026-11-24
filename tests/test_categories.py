"""Phase 4.10: custom categories."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_ADD, BTN_CANCEL
from app.db import init_db
from app.services import budgets, categories, periods, summaries, transactions
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()


def test_everyone_starts_with_the_built_in_lists(db):
    assert [k for k, _ in categories.choices(UID, "expense")] == ["food", "transport", "bills", "shopping", "fun", "other"]
    assert [k for k, _ in categories.choices(UID, "income")] == ["salary", "freelance", "business", "gift", "other"]


def test_add_rename_hide(db):
    rent = categories.add_category(UID, "expense", "🏠 Rent")
    assert rent["key"] == "rent"
    entry_id = transactions.add_expense(UID, 30000, "rent", "November")
    categories.rename_category(UID, "expense", "rent", "🏠 House rent")
    assert transactions.get_entry(UID, entry_id)["category_name"] == "🏠 House rent"
    categories.set_hidden(UID, "expense", "rent")
    assert "rent" not in dict(categories.choices(UID, "expense"))
    with pytest.raises(ValidationError):
        transactions.add_expense(UID, 5, "rent")
    categories.set_hidden(UID, "expense", "rent", False)
    assert "rent" in dict(categories.choices(UID, "expense"))


def test_hidden_categories_keep_their_past_entries_in_summaries(db):
    transactions.add_expense(UID, 120, "fun", "concert")
    budgets.set_budget(UID, "fun", 500)
    categories.set_hidden(UID, "expense", "fun")
    s = summaries.summary(UID, "month")
    assert s["expense_minor"] == 12000
    assert [(c["category"], c["label"], c["total_minor"]) for c in s["by_category"]] == [("fun", "🎉 Fun", 12000)]
    assert any(b["category"] == "fun" and b["spent_minor"] == 12000 for b in s["budgets"])
    assert budgets.month_total_for_category(UID, "fun", periods.month_start()) == 120


def test_an_entry_in_a_hidden_category_can_still_be_edited(db):
    entry_id = transactions.add_expense(UID, 10, "fun")
    categories.set_hidden(UID, "expense", "fun")
    entry, _ = transactions.update_entry(UID, entry_id, note="still fine")
    assert entry["category"] == "fun"


def test_rules(db):
    with pytest.raises(ValidationError, match="already"):
        categories.add_category(UID, "expense", "food")
    with pytest.raises(ValidationError, match="30"):
        categories.add_category(UID, "income", "x" * 31)
    for key, _ in categories.choices(UID, "income")[1:]:
        categories.set_hidden(UID, "income", key)
    with pytest.raises(ValidationError, match="at least one"):
        categories.set_hidden(UID, "income", "salary")
    assert categories.add_category(UID, "expense", "Transfer")["key"] == "transfer_2"   # never the reserved key


def test_same_name_allowed_in_the_other_type(db):
    categories.add_category(UID, "income", "🏠 Rent")         # rent received
    categories.add_category(UID, "expense", "🏠 Rent")        # rent paid
    transactions.add_expense(UID, 100, "rent", type_="income")
    transactions.add_expense(UID, 40, "rent")
    s = summaries.summary(UID, "month")
    assert (s["income_minor"], s["expense_minor"]) == (10000, 4000)


# --- bot ----------------------------------------------------------------------------
def test_bot_manage_categories(db):
    async def scenario():
        async with Harness() as h:
            out = await h.tap("cat:list:expense")
            assert "Expense categories" in out.texts[-1] and "Food" in out.texts[-1]
            await h.tap("cat:add:expense")
            out = await h.text("food")
            assert "already" in out.texts[0]
            out = await h.text("📚 School fees")
            assert "Added 📚 School fees" in out.texts[0]

            await h.tap("cat:pick:ren:expense")
            await h.tap("cat:ren:expense:school_fees")
            out = await h.text("📚 Tuition")
            assert "Renamed to 📚 Tuition" in out.texts[0]

            out = await h.tap("cat:pick:hide:expense")
            assert any(b["callback_data"] == "cat:hide:expense:fun" for b in out.buttons())
            out = await h.tap("cat:hide:expense:fun")
            assert "Hidden" in out.texts[-1] and "🎉 Fun" in out.texts[-1].split("Hidden")[1]

            await h.text(BTN_ADD)
            out = await h.text("50")
            labels = [b["text"] for b in out.buttons()]
            assert "📚 Tuition" in labels and "🎉 Fun" not in labels

            out = await h.tap("cat:list:income")
            assert "Income categories" in out.texts[-1]

    run(scenario())


def test_quick_entry_knows_custom_names(db):
    categories.add_category(UID, "expense", "🏠 Rent")

    async def scenario():
        async with Harness() as h:
            await h.text("25000 rent november")
            e = transactions.list_recent(UID)[0]
            assert (e["category"], e["note"]) == ("rent", "november")

    run(scenario())


def test_bot_cancel_naming(db):
    async def scenario():
        async with Harness() as h:
            await h.tap("cat:add:income")
            out = await h.text(BTN_CANCEL)
            assert "Cancelled" in out.texts[-1] and len(categories.choices(UID, "income")) == 5

    run(scenario())


# --- API ----------------------------------------------------------------------------
def test_api_categories(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=Harness().app)) as client:
        r = client.post("/api/categories", headers=headers, json={"type": "income", "name": "🏦 Interest"}).json()
        assert r["categories"]["income"][-1] == {"key": "interest", "label": "🏦 Interest", "hidden": False}
        e = client.post("/api/transactions", headers=headers,
                        json={"amount": 12, "type": "income", "category": "interest"}).json()["entry"]
        assert e["category_label"] == "🏦 Interest"
        r = client.patch("/api/categories/income/interest", headers=headers, json={"hidden": True}).json()
        assert r["categories"]["income"][-1]["hidden"] is True
        assert client.get("/api/me", headers=headers).json()["categories"]["income"][-1]["hidden"] is True
        assert client.post("/api/transactions", headers=headers,
                           json={"amount": 12, "type": "income", "category": "interest"}).status_code == 422
        assert client.get("/api/summary?period=month", headers=headers).json()["income_minor"] == 1200
        assert client.patch("/api/categories/income/nope", headers=headers, json={"name": "x"}).status_code == 422
