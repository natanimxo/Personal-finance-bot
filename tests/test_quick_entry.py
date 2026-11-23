"""Phase 4.1: quick entry."""
import pytest

from app.db import init_db
from app.services import accounts, transactions
from app.services.quick_entry import parse
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


# --- parser ----------------------------------------------------------------------
def p(text):
    r = parse(text)
    return r and (r.amount_minor, r.type, r.category, r.account, r.note)


def test_the_three_examples_from_the_plan():
    assert p("500 food lunch") == (50000, "expense", "food", None, "lunch")
    assert p("+20000 salary") == (2000000, "income", "salary", None, "")
    assert p("350 transport mpesa matatu") == (35000, "expense", "transport", "mobile_money", "matatu")


@pytest.mark.parametrize("text,amount", [("1,500 food", 150000), ("1500.50 food", 150050), ("+ 2,000.5 gift", 200050),
                                         (".5 food", 50), ("20,000 rent", 2000000)])
def test_commas_and_decimals(text, amount):
    assert parse(text).amount_minor == amount


def test_three_decimals_is_an_error():
    with pytest.raises(ValidationError, match="2 decimal"):
        parse("12.345 food")


def test_not_a_quick_entry():
    for text in ["hello", "food 500", "", "📋 History", "+food", "500food"]:
        assert parse(text) is None, text


def test_unknown_words_become_the_note_and_category_stays_empty():
    assert p("500 sugar and bread") == (50000, "expense", None, None, "sugar and bread")


def test_case_and_aliases():
    assert p("200 LUNCH at Java") == (20000, "expense", "food", None, "at Java")
    assert p("90 Taxi M-Pesa") == (9000, "expense", "transport", "mobile_money", "")
    assert p("1200 kplc bank") == (120000, "expense", "bills", "bank", "")


def test_first_match_wins_and_the_rest_is_note():
    assert p("500 food lunch dinner") == (50000, "expense", "food", None, "lunch dinner")
    assert p("350 transport mpesa matatu cash") == (35000, "expense", "transport", "mobile_money", "matatu cash")


def test_income_word_without_plus_is_income():
    assert p("20000 salary") == (2000000, "income", "salary", None, "")


def test_plus_never_picks_an_expense_category():
    assert p("+500 food") == (50000, "income", None, None, "food")


def test_note_length_is_checked():
    with pytest.raises(ValidationError, match="200"):
        parse("5 food " + "x" * 201)


# --- bot ---------------------------------------------------------------------------
@pytest.fixture
def db(fresh_db):
    init_db()


def test_bot_logs_the_three_examples_in_one_message_each(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text("500 food lunch")
            assert "Logged −500.00" in out.texts[0] and "Food" in out.texts[0] and "lunch" in out.texts[0]
            assert any(b.get("callback_data", "").startswith("undo:") for b in out.buttons())
            await h.text("+20000 salary")
            await h.text("350 transport mpesa matatu")
            got = [(e["type"], e["amount_minor"], e["category"], e["account"], e["note"])
                   for e in transactions.list_recent(UID)]
            assert got == [("expense", 35000, "transport", "mobile_money", "matatu"),
                           ("income", 2000000, "salary", "cash", ""),
                           ("expense", 50000, "food", "cash", "lunch")]

    run(scenario())


def test_unknown_category_shows_buttons_with_the_amount_kept(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text("750 bank sugar")
            assert "750.00" in out.texts[0]
            assert any(b.get("callback_data") == "qcat_food" for b in out.buttons())
            out = await h.tap("qcat_food")
            assert "Logged" in out.texts[-1]
            e = transactions.list_recent(UID)[0]
            assert (e["amount_minor"], e["category"], e["account"], e["note"]) == (75000, "food", "bank", "sugar")

    run(scenario())


def test_default_account_used_when_none_named(db):
    accounts.set_default_account(UID, "card")

    async def scenario():
        async with Harness() as h:
            await h.text("80 coffee")
            assert transactions.list_recent(UID)[0]["account"] == "card"

    run(scenario())


def test_undo_removes_the_entry(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text("500 food")
            undo = next(b["callback_data"] for b in out.buttons() if b.get("callback_data", "").startswith("undo:"))
            out = await h.tap(undo)
            assert "Undone" in out.texts[-1]
            assert transactions.list_recent(UID) == []
            await h.tap(undo)  # a second tap is harmless

    run(scenario())


def test_bad_amount_gets_a_reason(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text("12.345 food")
            assert "2 decimal places" in out.texts[0]

    run(scenario())


def test_a_number_typed_inside_the_add_flow_is_the_flows_amount(db):
    async def scenario():
        async with Harness() as h:
            await h.text("➕ Add Expense")
            out = await h.text("500")
            assert "Pick a category" in out.texts[0]
            assert transactions.list_recent(UID) == []

    run(scenario())
