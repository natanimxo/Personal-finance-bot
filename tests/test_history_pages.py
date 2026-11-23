"""Phase 4.9: History in the bot, 10 a page, Newer/Older, filter by type."""
import pytest

from app.bot.keyboards import BTN_HISTORY
from app.db import init_db
from app.services import transactions
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()
    for n in range(1, 26):                       # 25 expenses: amounts 1..25, newest is 25
        transactions.add_expense(UID, n, "food", f"item {n}")
    transactions.add_expense(UID, 1000, "salary", type_="income")
    transactions.add_transfer(UID, 50000, "cash", "bank")   # cents: KES 500


def button(out, text):
    return next(b["callback_data"] for b in out.buttons() if b["text"] == text)


def test_pages_of_ten_with_older_and_newer(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            assert "1–10" in out.texts[0] and "Older ➡️" in [b["text"] for b in out.buttons()]
            assert "Newer" not in " ".join(b["text"] for b in out.buttons())
            out = await h.tap(button(out, "Older ➡️"))
            assert "11–20" in out.texts[-1]
            out = await h.tap(button(out, "Older ➡️"))
            assert "21–27" in out.texts[-1] and "Older ➡️" not in [b["text"] for b in out.buttons()]
            out = await h.tap(button(out, "⬅️ Newer"))
            assert "11–20" in out.texts[-1]

    run(scenario())


def test_filter_by_type(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            out = await h.tap(button(out, "Income"))
            assert "<b>Income</b> · 1–1" in out.texts[-1] and "+KES 1,000" in out.texts[-1]
            out = await h.tap(button(out, "Transfers"))
            assert "🔁 KES 500" in out.texts[-1]
            out = await h.tap(button(out, "Expenses"))
            assert "1–10" in out.texts[-1] and "Salary" not in out.texts[-1]

    run(scenario())


def test_the_oldest_entry_can_be_reached_and_deleted(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            out = await h.tap(button(out, "Expenses"))
            out = await h.tap(button(out, "Older ➡️"))
            out = await h.tap(button(out, "Older ➡️"))
            assert "item 1" in out.texts[-1]                      # oldest expense, on page 3
            out = await h.tap(button(out, "25"))
            assert "item 1" in out.texts[-1]
            out = await h.tap(button(out, "🗑️ Delete"))
            assert "Deleted" in out.texts[-1]
            assert not any(e["note"] == "item 1" for e in transactions.list_entries(UID, limit=100)[0])

    run(scenario())


def test_open_then_back_and_edit_from_the_list(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            out = await h.tap(button(out, "Older ➡️"))
            out = await h.tap(button(out, "11"))
            out = await h.tap(button(out, "↩️ Back to the list"))
            assert "11–20" in out.texts[-1]
            out = await h.tap(button(out, "12"))
            out = await h.tap(button(out, "✏️ Edit"))
            assert "Editing" in out.texts[-1]

    run(scenario())


def test_after_a_restart_old_buttons_start_from_the_top(db):
    async def scenario():
        async with Harness() as h:
            out = await h.tap("hpg:all:2")                       # no saved pages: back to page 1
            assert "1–10" in out.texts[-1]

    run(scenario())
