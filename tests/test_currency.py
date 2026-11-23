"""Phase 4.6: the user's currency everywhere, formatted like KES 1,500."""
import pytest

from app.bot.keyboards import BTN_ACCOUNTS, BTN_BUDGETS, BTN_CANCEL, BTN_HISTORY, BTN_SETTINGS
from app.db import init_db
from app.services import budgets, prefs, transactions
from app.services.money import fmt
from tests.fake_telegram import UID, Harness, run


@pytest.mark.parametrize("minor,sign,expected", [
    (150000, False, "KES 1,500"), (150050, False, "KES 1,500.50"), (5, False, "KES 0.05"),
    (-20000, False, "\u2212KES 200"), (2000000, True, "+KES 20,000"), (0, True, "KES 0"),
    (123456789, False, "KES 1,234,567.89"),
])
def test_format(minor, sign, expected):
    assert fmt(minor, "KES", sign) == expected


@pytest.fixture
def db(fresh_db):
    init_db()


def test_new_users_get_the_default_currency(db):
    assert prefs.get_prefs(UID)["currency"] == "KES"


def test_every_bot_message_uses_the_users_currency(db):
    prefs.set_prefs(UID, "ETB")
    budgets.set_budget(UID, "food", 1000)

    async def scenario():
        async with Harness() as h:
            texts = []
            texts += (await h.text("950 food lunch")).texts                     # entry + budget warning
            texts += (await h.text(BTN_HISTORY)).texts
            texts += (await h.tap("sum_month")).texts
            texts += (await h.text(BTN_ACCOUNTS)).texts
            texts += (await h.text(BTN_BUDGETS)).texts
            texts += (await h.text("12 sugar")).texts                           # "which category?"
            joined = "\n".join(texts)
            assert "ETB 950" in joined and "ETB 1,000" in joined and "ETB 12" in joined
            assert "KES" not in joined and ".00" not in joined

    run(scenario())


def test_change_currency_in_bot_settings(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_SETTINGS)
            assert "Currency: <b>KES</b>" in out.texts[0] and "KES 1,500" in out.texts[0]
            await h.tap("set:currency")
            out = await h.tap("cur:ETB")
            assert "Currency set to ETB" in out.texts[-1]
            await h.tap("cur:other")
            out = await h.text("birr")
            assert "3-letter" in out.texts[0]
            out = await h.text("mwk")
            assert "Currency set to MWK" in out.texts[0]
            assert prefs.get_prefs(UID)["currency"] == "MWK"
            out = await h.tap("set:recap")
            assert prefs.get_prefs(UID)["recap_enabled"] is False and "recap: <b>off</b>" in out.texts[-1]

    run(scenario())


def test_cancel_typing_a_currency(db):
    async def scenario():
        async with Harness() as h:
            await h.tap("cur:other")
            out = await h.text(BTN_CANCEL)
            assert "Cancelled" in out.texts[-1] and prefs.get_prefs(UID)["currency"] == "KES"

    run(scenario())


def test_recap_uses_the_currency(db):
    from datetime import datetime, timezone

    from app.db import get_conn
    from app.services import periods
    from app.services.recap import recap_text

    prefs.set_prefs(UID, "USD")
    e = transactions.add_expense(UID, 1234.5, "food")
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = '2026-11-18T09:00:00' WHERE id = ?", (e,))
    start, end = periods.previous_week(datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert "USD 1,234.50" in recap_text(UID, start, end)
