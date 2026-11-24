"""The channel gate: kept in the database by numeric id, managed with admin commands,
off until /gate_on, and rotating per user every 30 days from their first day."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot import membership
from app.bot.keyboards import BTN_ADD, BTN_HISTORY
from app.db import get_conn, init_db
from app.services import gate, transactions, users
from tests.fake_telegram import CHAT, UID, USER, Harness, run

SEEDED = [-1002704031424, -1002905948541, -1004376927203, -1001992993907, -1001897854375, -1001200205264]
ONE, TWO, THREE = -1001111111111, -1002222222222, -1003333333333
ADMIN = 999


@pytest.fixture
def db(fresh_db, monkeypatch):
    init_db()
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)


@pytest.fixture
def three(db):
    """The gate on, with three channels of our own instead of the seeded six."""
    with get_conn() as conn:
        conn.execute("DELETE FROM gate_channels")
    for chat_id in (ONE, TWO, THREE):
        gate.add_channel(chat_id)
    gate.set_on(True)


def started_days_ago(user_id, days):
    users.register_user(user_id)
    when = (datetime.now(timezone.utc) - timedelta(days=days, hours=1)).replace(tzinfo=None).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE users SET first_start_at = ? WHERE user_id = ?", (when, user_id))


async def admin_says(h, text, forwarded_from=None, user_id=ADMIN):
    """The admin sends a command, optionally as a reply to a post forwarded from a channel."""
    n = h._next()
    sender = {**USER, "id": user_id}
    message = {"message_id": 1000 + n, "date": 0, "chat": {**CHAT, "id": user_id}, "from": sender, "text": text,
               "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]}
    if forwarded_from is not None:
        channel = {"id": forwarded_from, "type": "channel", "title": f"Title of {forwarded_from}"}
        message["reply_to_message"] = {
            "message_id": 500 + n, "date": 0, "chat": {**CHAT, "id": user_id}, "from": sender, "text": "a post",
            "forward_origin": {"type": "channel", "date": 0, "chat": channel, "message_id": 7}}
    return await h._process({"update_id": n, "message": message})


# --- stored in the database, seeded, off ---------------------------------------------------
def test_the_six_channels_are_seeded_in_order_and_the_gate_is_off(db):
    assert [c.chat_id for c in gate.channels()] == SEEDED
    assert gate.is_on() is False and gate.required_channel(5) is None


def test_only_numeric_ids_are_stored(db):
    for bad in ("@somechannel", "https://t.me/+abc", "12345", "abc"):
        with pytest.raises(gate.GateError):
            gate.add_channel(bad)
    with get_conn() as conn:
        schema = conn.execute("SELECT type FROM pragma_table_info('gate_channels') WHERE name = 'chat_id'").fetchone()
    assert schema[0] == "INTEGER"


def test_no_gate_settings_in_the_environment():
    for name in ("GATE_ENABLED", "GATE_CHANNELS", "REQUIRED_CHANNEL", "CHANNEL_INVITE_LINK"):
        assert not hasattr(config, name)


# --- rotation: no free month -----------------------------------------------------------------
@pytest.mark.parametrize("days,expected", [
    (0, 0), (29, 0),          # days 1-30: channel 1 (no free period)
    (30, 1), (59, 1),         # days 31-60: channel 2
    (60, 2), (89, 2),         # days 61-90: channel 3
    (90, 0), (125, 1),        # and round again, automatically
])
def test_rotation(days, expected):
    assert gate.channel_index_for(days, 3) == expected


def test_each_user_rotates_on_their_own_clock(three):
    started_days_ago(1, 0)
    started_days_ago(2, 35)
    started_days_ago(3, 65)
    started_days_ago(4, 95)
    assert [gate.required_channel(u).chat_id for u in (1, 2, 3, 4)] == [ONE, TWO, THREE, ONE]
    assert gate.stats() == {"free": 0, "channels": [2, 1, 1]}


def test_removing_a_channel_shifts_the_rest(three):
    started_days_ago(1, 35)                                       # on channel 2
    gone = gate.remove_channel(1)
    assert gone.chat_id == ONE and [c.chat_id for c in gate.channels()] == [TWO, THREE]
    assert gate.required_channel(1).chat_id == THREE              # now the 2nd of two
    with pytest.raises(gate.GateError):
        gate.remove_channel(5)


# --- statuses (still counted the same) -------------------------------------------------------
@pytest.mark.parametrize("status,is_member,joined", [
    ("creator", True, True), ("administrator", True, True), ("member", True, True),
    ("restricted", True, True), ("restricted", False, False), ("left", False, False), ("kicked", False, False),
])
def test_member_statuses(three, status, is_member, joined):
    async def scenario():
        async with Harness() as h:
            h.request.member_status, h.request.member_is_member = status, is_member
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5, live=True) is joined
            assert h.request.member_chats == [str(ONE)]           # asked by numeric id

    run(scenario())


# --- the join screen: title and invite link from Telegram, cached 24 h -------------------------
def test_join_screen_uses_the_live_title_and_a_fresh_invite_link(three):
    started_days_ago(UID, 40)                                     # channel 2's month

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert f"This month's channel: Title of {TWO}" in out.texts[0]
            join, joined = out.buttons()
            assert join["text"] == f"📢 Join Title of {TWO}" and join["url"].startswith("https://t.me/+invite1_")
            assert joined == {"text": "✅ I've joined", "callback_data": "recheck_sub"}

            await h.text(BTN_HISTORY)                              # within 24 h: cached
            assert h.request.invite_links == 1
            assert sum(1 for e, _ in h.request.calls if e == "getChat") == 1

            with get_conn() as conn:                               # a day later: fetched again
                conn.execute("UPDATE gate_channels SET title_at = '2000-01-01T00:00:00', "
                             "invite_link_at = '2000-01-01T00:00:00'")
            out = await h.text(BTN_HISTORY)
            assert h.request.invite_links == 2 and "+invite2_" in out.buttons()[0]["url"]

            h.request.member_status = "member"
            out = await h.tap("recheck_sub")
            assert "You're in this month's channel" in out.texts[0]

    run(scenario())


def test_gate_off_means_no_checks(three):
    gate.set_on(False)
    started_days_ago(UID, 40)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0

    run(scenario())


def test_the_admin_is_exempt(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0

    run(scenario())


def test_never_blocked_in_the_middle_of_an_entry(three):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)                  # checked here: a member
            h.request.member_status = "left"
            membership.membership_cache.clear()
            await h.text("25")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            out = await h.tap("skip_note")
            assert "Logged" in out.texts[-1] and h.request.member_checks == 1

    run(scenario())


def test_api_uses_the_same_rule(three, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    harness = Harness()
    started_days_ago(8, 65)                                       # channel 3's month
    with TestClient(create_app(application=harness.app)) as client:
        harness.request.member_status = "left"
        r = client.get("/api/me", headers={"Authorization": "tma " + make_init_data({"id": 8}, config.BOT_TOKEN)})
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert detail["channel"] == f"Title of {THREE}" and detail["join_link"].startswith("https://t.me/+invite")


# --- admin commands ----------------------------------------------------------------------------
@pytest.fixture
def admin(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)


def test_gate_add_from_a_forwarded_post(admin):
    async def scenario():
        async with Harness() as h:
            new = -1004444444444
            out = await admin_says(h, "/gate_add", forwarded_from=new)
            assert f"Added Title of {new}" in out.texts[0] and "as channel 4" in out.texts[0]
            assert [c.chat_id for c in gate.channels()][-1] == new
            out = await admin_says(h, "/gate_add", forwarded_from=new)
            assert "already in the rotation" in out.texts[0]

    run(scenario())


def test_gate_add_refuses_a_channel_where_the_bot_is_not_admin(admin):
    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = set()
            out = await admin_says(h, "/gate_add", forwarded_from=-1005555555555)
            assert "not an administrator" in out.texts[0]
            assert len(gate.channels()) == 3

    run(scenario())


def test_gate_add_needs_a_forwarded_post_or_a_numeric_id(admin):
    async def scenario():
        async with Harness() as h:
            assert "Forward any post" in (await admin_says(h, "/gate_add")).texts[0]
            assert "numeric id" in (await admin_says(h, "/gate_add @channel")).texts[0]
            out = await admin_says(h, "/gate_add -1006666666666")
            assert "as channel 4" in out.texts[0]

    run(scenario())


def test_gate_remove_list_on_off(admin):
    started_days_ago(1, 3)
    started_days_ago(2, 33)

    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {str(ONE), str(THREE)}
            text = (await admin_says(h, "/gate_list")).texts[0]
            assert f"1. Title of {ONE} (<code>{ONE}</code>) · bot admin ✅" in text
            assert f"2. Title of {TWO} (<code>{TWO}</code>) · bot admin ❌" in text
            assert text.count("1 user(s) on it now") == 2

            text = (await admin_says(h, "/gate_remove 2")).texts[0]
            assert f"Removed Title of {TWO}" in text and f"2. Title of {THREE}" in text
            assert "number from /gate_list" in (await admin_says(h, "/gate_remove")).texts[0]

            out = await admin_says(h, "/gate_off")
            assert "off" in out.texts[0] and gate.is_on() is False
            out = await admin_says(h, "/gate_status")
            assert "Channel gate</b>: off" in out.texts[0]
            h.request.bot_admin_in = {str(ONE)}
            out = await admin_says(h, "/gate_on")
            assert "on" in out.texts[0] and gate.is_on() is True
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and "isn't an administrator" in p["text"]]
            assert alerts and str(THREE) in alerts[0]

    run(scenario())


def test_gate_commands_are_admin_only(admin):
    async def scenario():
        async with Harness() as h:
            for command in ("/gate_list", "/gate_on", "/gate_off", "/gate_remove 1", "/gate_add -1007777777777"):
                assert await admin_says(h, command, user_id=UID) == [], command
            assert len(gate.channels()) == 3 and gate.is_on()

    run(scenario())


def test_startup_alert_for_channels_without_the_bot_as_admin(admin):
    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {str(ONE)}
            await membership.startup_check(h.app.bot)
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == ADMIN]
            assert len(alerts) == 1 and f"{TWO}, {THREE}" in alerts[0]

    run(scenario())


@pytest.mark.parametrize("error", ["Bad Request: member list is inaccessible",   # in it, but not admin
                                   "Bad Request: chat not found"])                # can't see the channel
def test_a_channel_the_bot_cant_check_lets_users_through_and_alerts(three, monkeypatch, error):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)

    async def scenario():
        async with Harness() as h:
            h.request.member_error, h.request.member_error_text = True, error
            ctx = SimpleNamespace(bot=h.app.bot)
            assert await membership.is_subscribed(ctx, 5) is True
            assert await membership.is_subscribed(ctx, 6) is True
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == ADMIN]
            assert len(alerts) == 1 and str(ONE) in alerts[0]

    run(scenario())


def test_other_telegram_trouble_uses_the_last_known_answer(three):
    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            h.request.member_error = True                       # e.g. a temporary failure
            assert await membership.is_subscribed(ctx, 5) is False          # never seen: not let in
            h.request.member_error = False
            assert await membership.is_subscribed(ctx, 5, live=True) is True
            h.request.member_error = True
            assert await membership.is_subscribed(ctx, 5, live=True) is True   # last known: a member

    run(scenario())
