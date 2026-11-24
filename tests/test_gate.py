"""The channel gate: off by default, a free first month, then one channel per month
in rotation, checked only when an action starts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot import membership
from app.bot.keyboards import BTN_ADD, BTN_HISTORY
from app.db import get_conn, init_db
from app.services import gate, transactions, users
from tests.fake_telegram import UID, Harness, run

CHANNELS = "@chan_one|https://t.me/chan_one,-1001234567890|https://t.me/+privateInvite,@chan_three|"


@pytest.fixture
def db(fresh_db, monkeypatch):
    init_db()
    monkeypatch.setattr(gate, "FREE_DAYS", 30)          # the real rules
    monkeypatch.setattr(config, "GATE_CHANNELS", CHANNELS)
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)


def started_days_ago(user_id, days):
    users.register_user(user_id)
    when = (datetime.now(timezone.utc) - timedelta(days=days, hours=1)).replace(tzinfo=None).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE users SET first_start_at = ? WHERE user_id = ?", (when, user_id))


# --- 1. which statuses count as joined ------------------------------------------------------
@pytest.mark.parametrize("status,is_member,joined", [
    ("creator", True, True),            # the channel owner
    ("administrator", True, True),
    ("member", True, True),
    ("restricted", True, True),         # restricted but still in the channel
    ("restricted", False, False),       # restricted and not in it
    ("left", False, False),
    ("kicked", False, False),
])
def test_member_statuses(fresh_db, status, is_member, joined):
    init_db()

    async def scenario():
        async with Harness() as h:
            h.request.member_status, h.request.member_is_member = status, is_member
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5, live=True) is joined

    run(scenario())


def test_the_bot_not_being_admin_lets_users_through_and_alerts_the_admin(fresh_db, monkeypatch):
    """Telegram's "member list is inaccessible": our setup problem, not the user's."""
    init_db()
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)

    async def scenario():
        async with Harness() as h:
            h.request.member_error, h.request.member_error_text = True, "Bad Request: member list is inaccessible"
            ctx = SimpleNamespace(bot=h.app.bot)
            assert await membership.is_subscribed(ctx, 5) is True
            assert await membership.is_subscribed(ctx, 6) is True
            alerts = [p for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == 999]
            assert len(alerts) == 1 and "isn't an administrator of @test_channel" in alerts[0]["text"]

    run(scenario())


# --- channel list format --------------------------------------------------------------------
def test_channel_list_format():
    found, problems = gate.parse_channels(CHANNELS)
    assert [(c.chat_id, c.link, c.number) for c in found] == [
        ("@chan_one", "https://t.me/chan_one", 1),
        ("-1001234567890", "https://t.me/+privateInvite", 2),
        ("@chan_three", "https://t.me/chan_three", 3)]   # a missing link is made from the @username
    assert problems == []


def test_an_invite_link_is_not_a_channel_id():
    found, problems = gate.parse_channels("https://t.me/+abc|https://t.me/+abc,@ok_channel|x")
    assert [c.chat_id for c in found] == ["@ok_channel"] and "not a channel id" in problems[0]
    assert gate.parse_channels("", "t.me/HustleToMillions", "")[1]


def test_at_most_six_channels():
    found, problems = gate.parse_channels(",".join(f"@channel{i}|" for i in range(1, 9)))
    assert len(found) == 6 and len(problems) == 2


def test_the_old_one_channel_settings_still_work(monkeypatch):
    monkeypatch.setattr(config, "GATE_CHANNELS", "")
    monkeypatch.setattr(config, "REQUIRED_CHANNEL", "@HustleToMillions")
    monkeypatch.setattr(config, "CHANNEL_INVITE_LINK", "https://t.me/HustleToMillions")
    assert [(c.chat_id, c.link) for c in gate.channels()] == [("@HustleToMillions", "https://t.me/HustleToMillions")]


# --- 2. off by default ----------------------------------------------------------------------
def test_gate_off_means_no_checks_at_all(db, monkeypatch):
    monkeypatch.setattr(config, "GATE_ENABLED", False)
    started_days_ago(UID, 45)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0]
            assert h.request.member_checks == 0

    run(scenario())


def test_default_is_off(monkeypatch):
    import importlib
    monkeypatch.delenv("GATE_ENABLED", raising=False)
    fresh = importlib.reload(importlib.import_module("app.config"))
    try:
        assert fresh.GATE_ENABLED is False
    finally:
        importlib.reload(fresh)


# --- the free month and the rotation --------------------------------------------------------
@pytest.mark.parametrize("days,expected", [
    (0, None), (29, None),                      # days 1-30: free
    (30, 0), (59, 0),                           # days 31-60: channel 1
    (60, 1), (89, 1),                           # days 61-90: channel 2
    (90, 2), (119, 2),                          # days 91-120: channel 3
    (120, 0), (150, 1),                         # and round again
])
def test_rotation(days, expected, monkeypatch):
    monkeypatch.setattr(gate, "FREE_DAYS", 30)
    assert gate.channel_index_for(days, 3) == expected


def test_each_user_rotates_from_their_own_start(db):
    started_days_ago(1, 10)
    started_days_ago(2, 40)
    started_days_ago(3, 70)
    assert gate.required_channel(1) is None
    assert gate.required_channel(2).chat_id == "@chan_one"
    assert gate.required_channel(3).chat_id == "-1001234567890"
    assert gate.stats() == {"free": 1, "channels": [1, 1, 0]}


def test_first_contact_starts_the_free_month(db):
    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0
            assert gate.days_since(gate.first_start(UID)) == 0

    run(scenario())


def test_only_this_months_channel_is_needed(db):
    started_days_ago(UID, 70)                                    # channel 2's month

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            h.request.statuses[("-1001234567890", UID)] = "member"   # in channel 2 only
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0]
            assert h.request.member_chats == ["-1001234567890"]

    run(scenario())


def test_the_join_screen_names_this_months_channel(db):
    started_days_ago(UID, 40)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "This month's channel: @chan_one" in out.texts[0]
            buttons = out.buttons()
            assert buttons[0] == {"text": "📢 Join @chan_one", "url": "https://t.me/chan_one"}
            assert buttons[1]["text"] == "✅ I've joined" and buttons[1]["callback_data"] == "recheck_sub"

            out = await h.tap("recheck_sub")                            # not yet
            assert any(c[0] == "answerCallbackQuery" and "Not in this month's channel" in c[1].get("text", "")
                       for c in h.request.calls)
            h.request.member_status = "member"                          # joined
            out = await h.tap("recheck_sub")
            assert "You're in this month's channel" in out.texts[0]

    run(scenario())


def test_the_admin_is_always_exempt(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
    started_days_ago(UID, 40)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0

    run(scenario())


def test_never_blocked_in_the_middle_of_an_entry(db):
    started_days_ago(UID, 40)

    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)                  # checked here: a member
            h.request.member_status = "left"       # leaves halfway (or the month turns)
            membership.membership_cache.clear()
            await h.text("25")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            out = await h.tap("skip_note")
            assert "Logged" in out.texts[-1]
            assert len(transactions.list_recent(UID)) == 1
            assert h.request.member_checks == 1    # only when the entry started

    run(scenario())


# --- the Mini App -----------------------------------------------------------------------------
def test_api_uses_the_same_rule(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    harness = Harness()

    def auth(uid):
        return {"Authorization": "tma " + make_init_data({"id": uid}, config.BOT_TOKEN)}

    with TestClient(create_app(application=harness.app)) as client:
        harness.request.member_status = "left"
        assert client.get("/api/me", headers=auth(7)).status_code == 200       # first visit: free month
        started_days_ago(8, 65)
        r = client.get("/api/me", headers=auth(8))
        assert r.status_code == 403
        assert r.json()["detail"] == {"error": "not_subscribed", "join_link": "https://t.me/+privateInvite",
                                      "channel": "Title of -1001234567890"}



# --- startup check and /gate_status -------------------------------------------------------------
def test_startup_alerts_the_admin_about_channels_where_the_bot_is_not_admin(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)

    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {"@chan_one"}
            await membership.startup_check(h.app.bot)
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == 999]
            assert len(alerts) == 1
            assert "-1001234567890, @chan_three" in alerts[0] and "@chan_one" not in alerts[0]

    run(scenario())


def test_startup_check_does_nothing_when_the_gate_is_off(db, monkeypatch):
    monkeypatch.setattr(config, "GATE_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)

    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = set()
            await membership.startup_check(h.app.bot)
            assert h.request.sent == []

    run(scenario())


def test_gate_status_for_the_admin(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
    started_days_ago(1, 5)
    started_days_ago(2, 35)
    started_days_ago(3, 36)

    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {"@chan_one", "@chan_three"}
            out = await h.text("/gate_status")
            text = out.texts[0]
            assert "Channel gate</b>: on" in text
            assert "1. Title of @chan_one (@chan_one): bot admin ✅, 2 user(s)" in text
            assert "2. Title of -1001234567890 (-1001234567890): bot admin ❌, 0 user(s)" in text
            assert "bot admin ✅, 0 user(s)" in text.split("3.")[1]
            assert "free first month: 1 user(s)" in text            # user 1 (the admin isn't counted)

    run(scenario())


def test_gate_status_is_admin_only(db):
    async def scenario():
        async with Harness() as h:
            assert await h.text("/gate_status") == []

    run(scenario())
