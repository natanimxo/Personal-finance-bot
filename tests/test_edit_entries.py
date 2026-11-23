"""Phase 4.2: editing entries from the bot's History."""
import pytest

from app.bot.keyboards import BTN_CANCEL, BTN_HISTORY, BTN_SUMMARY
from app.db import init_db
from app.services import accounts, budgets, transactions
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def entry(fresh_db):
    init_db()
    return transactions.add_expense(UID, 50, "food", "lunch", account="cash")


def test_history_has_edit_next_to_delete(entry):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            assert [b["text"] for b in out.buttons(1)] == ["✏️ Edit", "🗑️ Delete"]

    run(scenario())


def test_change_amount_category_account_and_note(entry):
    async def scenario():
        async with Harness() as h:
            out = await h.tap(f"edit:{entry}")
            assert "Editing" in out.texts[-1]
            assert {b["callback_data"] for b in out.buttons()} >= {f"edf:amount:{entry}", f"edcat:{entry}",
                                                                   f"edacc:{entry}", f"edf:note:{entry}"}
            await h.tap(f"edf:amount:{entry}")
            out = await h.text("1,250.50")
            assert "1250.50" in out.texts[-1]

            out = await h.tap(f"edcat:{entry}")
            assert any(b["callback_data"] == f"edsetcat:{entry}:transport" for b in out.buttons())
            await h.tap(f"edsetcat:{entry}:transport")

            await h.tap(f"edacc:{entry}")
            await h.tap(f"edsetacc:{entry}:mobile_money")

            await h.tap(f"edf:note:{entry}")
            await h.text("matatu home")
            out = await h.tap(f"eddone:{entry}")
            assert "Saved" in out.texts[-1]

            e = transactions.get_entry(UID, entry)
            assert (e["amount_minor"], e["category"], e["account"], e["note"]) == (125050, "transport", "mobile_money", "matatu home")

    run(scenario())


def test_an_edit_updates_balances_summaries_and_budgets(entry):
    budgets.set_budget(UID, "food", 100)

    async def scenario():
        async with Harness() as h:
            await h.tap(f"edf:amount:{entry}")
            out = await h.text("90")
            assert "90% of your" in out.texts[-1]           # the budget warning reflects the edit
            assert accounts.account_balances(UID) == {"cash": -90.0}
            await h.tap(f"edacc:{entry}")
            await h.tap(f"edsetacc:{entry}:bank")
            assert accounts.account_balances(UID) == {"bank": -90.0}
            out = await h.tap("sum_month")
            assert "Expenses: 90.00" in out.texts[-1]

    run(scenario())


def test_bad_amount_keeps_asking_and_cancel_leaves_it_unchanged(entry):
    async def scenario():
        async with Harness() as h:
            await h.tap(f"edf:amount:{entry}")
            out = await h.text("12.345")
            assert "2 decimal places" in out.texts[0]
            out = await h.text(BTN_CANCEL)
            assert "Cancelled" in out.texts[-1]
            assert transactions.get_entry(UID, entry)["amount_minor"] == 5000

    run(scenario())


def test_clearing_the_note_and_menu_button_mid_edit(entry):
    async def scenario():
        async with Harness() as h:
            await h.tap(f"edf:note:{entry}")
            await h.text("-")
            assert transactions.get_entry(UID, entry)["note"] == ""
            await h.tap(f"edf:note:{entry}")
            out = await h.text(BTN_SUMMARY)                  # leaves the edit
            assert "Pick a period" in out.texts[-1]
            assert transactions.get_entry(UID, entry)["note"] == ""

    run(scenario())


def test_cannot_edit_someone_elses_entry(entry):
    theirs = transactions.add_expense(999, 10, "food")

    async def scenario():
        async with Harness() as h:
            await h.tap(f"edsetacc:{theirs}:bank")
            assert transactions.get_entry(999, theirs)["account"] == "cash"

    run(scenario())
