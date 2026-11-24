"""Switching to a new bot (new token): its own invite links and command list, no
hardcoded username anywhere; and the Mini App tip for people who log by hand."""
import json
import re
from pathlib import Path

import pytest

from app import config
from app.bot import commands, membership
from app.bot.keyboards import BTN_ADD
from app.db import get_conn, init_db
from app.services import gate, users
from tests.fake_telegram import UID, Harness, run

ROOT = Path(__file__).resolve().parent.parent
ONE = -1001111111111


def j(value):
    """Telegram parameters arrive as JSON text or already decoded, depending on the call."""
    return json.loads(value) if isinstance(value, str) else value


@pytest.fixture
def db(fresh_db, monkeypatch):
    init_db()
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)


# --- 2. the old bot's invite links are forgotten ---------------------------------------------------------
def test_invite_links_are_cleared_when_the_bot_changes(db):
    gate.store_invite_link(gate.channels()[0].chat_id, "https://t.me/+oldbot")
    assert gate.note_bot(111) is True                              # first time we know a bot: old links go
    assert all(c.invite_link is None for c in gate.channels())
    gate.store_invite_link(gate.channels()[0].chat_id, "https://t.me/+mine")
    assert gate.note_bot(111) is False                             # same bot: links are kept
    assert gate.channels()[0].invite_link == "https://t.me/+mine"
    assert gate.note_bot(222) is True                              # a new token: forgotten again
    assert all(c.invite_link is None for c in gate.channels())


def test_startup_with_the_gate_on_makes_the_new_bots_own_links(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)
    for c in gate.channels():
        gate.store_invite_link(c.chat_id, "https://t.me/+fromTheOldBot")
    gate.set_on(True)

    async def scenario():
        async with Harness() as h:
            await membership.startup_check(h.app.bot)
            links = [c.invite_link for c in gate.channels()]
            assert all(links) and "fromTheOldBot" not in " ".join(links)
            assert len(set(links)) == 6 and h.request.invite_links == 6

    run(scenario())


# --- 5. the command list --------------------------------------------------------------------------------
def test_command_list_for_everyone_and_the_admin(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)

    async def scenario():
        async with Harness() as h:
            await commands.set_commands(h.app.bot)
            calls = [p for e, p in h.request.calls if e == "setMyCommands"]
            assert len(calls) == 2
            everyone = [c["command"] for c in j(calls[0]["commands"])]
            admin = [c["command"] for c in j(calls[1]["commands"])]
            assert everyone == ["start", "help", "settings", "export", "cancel"]
            assert admin[:5] == everyone and {"gate_on", "gate_off", "gate_list", "backup_now"} <= set(admin)
            assert j(calls[1]["scope"]) == {"type": "chat", "chat_id": 999}
            for c in j(calls[1]["commands"]):
                assert 3 <= len(c["description"]) <= 256 and re.fullmatch(r"[a-z0-9_]{1,32}", c["command"])

    run(scenario())


def test_every_registered_command_is_in_the_list():
    source = (ROOT / "app" / "bot" / "conversations.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'CommandHandler\("(\w+)"', source))
    registered |= {"gate_add", "gate_remove", "gate_list", "gate_status", "gate_stats", "gate_schedule", "gate_on",
                   "gate_off"}
    assert registered - {"restore"} <= set(commands.USER_COMMANDS + commands.ADMIN_COMMANDS)


# --- 4. no hardcoded bot username -------------------------------------------------------------------------
def test_no_bot_username_is_written_into_the_code_or_docs():
    allowed = {"@userinfobot", "@botfather", "@yourchannel", "@username", "@types"}
    found = []
    for path in [*ROOT.joinpath("app").rglob("*"), *ROOT.joinpath("docs").rglob("*"), ROOT / "README.md",
                 ROOT / ".env.example"]:
        if path.suffix not in (".py", ".md", ".js", ".html", ".sql", ".example", ""):
            continue
        if path.is_file():
            for name in re.findall(r"@[A-Za-z0-9_]*[Bb]ot\b", path.read_text(encoding="utf-8", errors="ignore")):
                if name.lower() not in allowed:
                    found.append((path.name, name))
    assert found == []


# --- the Mini App tip ----------------------------------------------------------------------------------
@pytest.fixture
def app_url(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")


def tips(h):
    return [p for e, p in h.request.sent if e == "sendMessage" and "Tip" in p.get("text", "")]


def test_tip_after_the_first_entry_then_every_tenth(db, app_url):
    async def scenario():
        async with Harness() as h:
            await h.text("5 food a")                                   # 1st entry logged in the bot
            sent = tips(h)
            assert len(sent) == 1 and "Mini App" in sent[0]["text"]
            button = j(sent[0]["reply_markup"])["inline_keyboard"][0][0]
            assert button == {"text": "📱 Open the app", "web_app": {"url": "https://example.test/"}}
            for i in range(2, 10):                                      # entries 2 to 9: quiet
                await h.text(f"5 food {i}")
                assert tips(h) == []
            await h.text("5 food 10")                                   # the 10th
            assert len(tips(h)) == 1
            await h.text(BTN_ADD)                                       # guided flow counts too
            await h.text("7")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            await h.tap("skip_note")
            assert tips(h) == []                                        # entry 11

    run(scenario())


def test_guided_flow_also_gets_the_tip(db, app_url):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("7")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            await h.tap("skip_note")
            assert len(tips(h)) == 1

    run(scenario())


def test_nobody_who_uses_the_app_is_nudged(db, app_url):
    users.register_user(UID)
    users.app_opened(UID)

    async def scenario():
        async with Harness() as h:
            await h.text("5 food a")
            assert tips(h) == []

    run(scenario())
    assert users.bot_entry_logged(UID) == (2, True)                    # still counted, never nudged


def test_no_tip_without_an_https_address(db, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")

    async def scenario():
        async with Harness() as h:
            await h.text("5 food a")
            assert tips(h) == []

    run(scenario())


def test_opening_the_mini_app_marks_the_user(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    gate.set_on(False)
    with TestClient(create_app(application=Harness().app)) as client:
        client.get("/api/me", headers={"Authorization": "tma " + make_init_data({"id": 31}, config.BOT_TOKEN)})
    with get_conn() as conn:
        assert conn.execute("SELECT app_seen_at FROM users WHERE user_id = 31").fetchone()[0]


def test_a_failing_tip_never_breaks_logging(db, app_url):
    from app.bot import app_hint

    class DownBot:
        async def send_message(self, *a, **k):
            raise RuntimeError("telegram is down")

    users.register_user(UID)
    run(app_hint.suggest_mini_app(DownBot(), UID, UID))                 # must not raise
