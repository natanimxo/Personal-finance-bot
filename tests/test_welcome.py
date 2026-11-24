"""The /start welcome (new and returning users, and after the first setup) and /help."""
import pytest

from app import config
from app.bot.keyboards import BTN_ACCOUNTS, BTN_ADD, BTN_ADD_INCOME, BTN_BUDGETS, BTN_HISTORY, BTN_SETTINGS, BTN_SUMMARY
from app.db import init_db
from app.strings import EN, t
from app.web.server import mini_app_url
from tests.fake_telegram import UID, Harness, run

WELCOME = (
    "👋 <b>Welcome to Wallet Buddy!</b>\n"
    "Track your spending and income for free.\n\n"
    "📱 Tap <b>Open App</b> for the full experience: charts, budgets and easy editing.\n"
    "Or use the buttons below for quick entries right here in the chat."
)


@pytest.fixture
def db(fresh_db):
    init_db()


@pytest.fixture
def app_url(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")


def test_the_welcome_text_is_exact_and_in_the_strings_file():
    assert EN["start.welcome"] == WELCOME and t("start.welcome") == WELCOME
    assert t("start.open_app") == "📱 Open App"


def test_start_for_a_returning_user_has_the_open_app_button_and_keeps_the_menu(db, app_url):
    async def scenario():
        async with Harness() as h:
            out = await h.text("/start")
            assert out.texts[0] == WELCOME
            # the inline button under the welcome: a Web App with the same URL as the menu button
            assert out.buttons(0) == [{"text": "📱 Open App", "web_app": {"url": mini_app_url()}}]
            assert not out.has_main_keyboard(0)                       # one kind of keyboard per message...
            assert out.texts[1] == "👇 Menu" and out.has_main_keyboard(1)   # ...so the reply keyboard follows
            assert len(out) == 2

    run(scenario())


def test_the_inline_button_uses_the_same_url_as_the_menu_button(db, app_url, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from app.services import gate
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    gate.set_on(False)
    harness = Harness()
    with TestClient(create_app(application=harness.app)):
        menu = [p for e, p in harness.request.calls if e == "setChatMenuButton"][0]["menu_button"]
        menu = menu if isinstance(menu, dict) else json.loads(menu)
        assert menu["web_app"]["url"] == mini_app_url() == "https://example.test/"


def test_without_an_https_address_the_welcome_itself_carries_the_menu(db, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")

    async def scenario():
        async with Harness() as h:
            out = await h.text("/start")
            assert len(out) == 1 and out.texts[0] == WELCOME and out.has_main_keyboard(0)

    run(scenario())


def test_new_users_get_the_welcome_after_currency_and_timezone(db, app_url):
    async def scenario():
        async with Harness(setup=None) as h:
            out = await h.text("/start")
            assert "Which currency" in out.texts[0] and WELCOME not in out.texts   # setup comes first
            await h.tap("ob:cur:USD")
            out = await h.tap("tz:z:Europe/Berlin")
            assert out.texts[1] == "🎉 All set! Your week starts on Monday and recaps arrive at 08:00 your time."
            assert out.texts[2] == WELCOME
            assert out.buttons(2) == [{"text": "📱 Open App", "web_app": {"url": mini_app_url()}}]
            assert out.has_main_keyboard(3)
            out = await h.text("/start")                                     # and again for a returning user
            assert out.texts[0] == WELCOME

    run(scenario())


def test_help_has_the_feature_list_and_no_recap_schedule(db, app_url):
    async def scenario():
        async with Harness() as h:
            out = await h.text("/help")
            return out.texts[0]

    text = run(scenario())
    for button in (BTN_ADD, BTN_ADD_INCOME, BTN_HISTORY, BTN_SUMMARY, BTN_BUDGETS, BTN_ACCOUNTS, BTN_SETTINGS):
        assert button in text
    assert "You'll get a weekly and monthly summary." in text
    for word in ("Monday", "08:00", "1st", "every", "o'clock"):
        assert word not in text, word
    assert "500 food lunch" in text


def test_the_welcome_no_longer_lists_features_or_recap_times():
    for word in ("Monday", "08:00", "1st", "recap", "Add Expense", "History", "Summary", "Budgets", "Accounts"):
        assert word not in WELCOME, word
