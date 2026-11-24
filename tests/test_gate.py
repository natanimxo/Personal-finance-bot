"""The channel gate (final spec): in the database by numeric id, off until /gate_on,
30 free days, then one channel per 30-day period per user; users must stay in the
current channel; one stored invite link per channel; events counted per channel."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot import membership
from app.bot.keyboards import BTN_ADD, BTN_HISTORY
from app.db import get_conn, init_db
from app.services import gate, users
from tests.fake_telegram import CHAT, UID, USER, Harness, run

SEEDED = [-1002704031424, -1002905948541, -1004376927203, -1001992993907, -1001897854375, -1001200205264]
ONE, TWO, THREE = -1001111111111, -1002222222222, -1003333333333
LINKS = {ONE: "https://t.me/+one", TWO: "https://t.me/+two", THREE: "https://t.me/+three"}
ADMIN = 999


@pytest.fixture
def db(fresh_db, monkeypatch):
    init_db()
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)


@pytest.fixture
def three(db):
    """The gate on, with three channels of our own (each with its stored invite link)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM gate_channels")
    for chat_id in (ONE, TWO, THREE):
        gate.add_channel(chat_id)
        gate.store_invite_link(chat_id, LINKS[chat_id])
    gate.set_on(True)


def started_days_ago(user_id, days):
    """`days` whole days since first contact: 0 is day 1, 30 is day 31."""
    users.register_user(user_id)
    when = (datetime.now(timezone.utc) - timedelta(days=days, hours=1)).replace(tzinfo=None).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE users SET first_start_at = ? WHERE user_id = ?", (when, user_id))


def events(user_id=None):
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, channel_id, period_number, event FROM gate_events ORDER BY id").fetchall()
    return [(r["channel_id"], r["period_number"], r["event"]) for r in rows if user_id in (None, r["user_id"])]


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


# --- 1. status and setup ---------------------------------------------------------------------------
def test_the_six_channels_are_stored_by_id_in_order_and_the_gate_is_off(db):
    assert [c.chat_id for c in gate.channels()] == SEEDED
    assert gate.is_on() is False and gate.position(5) is None
    with get_conn() as conn:
        kind = conn.execute("SELECT type FROM pragma_table_info('gate_channels') WHERE name = 'chat_id'").fetchone()[0]
    assert kind == "INTEGER"
    for bad in ("@somechannel", "https://t.me/+abc", "12345"):
        with pytest.raises(gate.GateError):
            gate.add_channel(bad)


def test_no_gate_settings_in_the_environment():
    for name in ("GATE_ENABLED", "GATE_CHANNELS", "REQUIRED_CHANNEL", "CHANNEL_INVITE_LINK"):
        assert not hasattr(config, name)


def test_the_webhook_asks_for_chat_member_updates():
    from telegram import Update
    assert "chat_member" in Update.ALL_TYPES   # what start_bot passes as allowed_updates


def test_admin_is_exempt(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
    started_days_ago(UID, 40)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0

    run(scenario())


# --- 3. rotation --------------------------------------------------------------------------------------
@pytest.mark.parametrize("day,expected", [
    (1, None), (30, None),           # days 1-30: free
    (31, 0), (60, 0),                # days 31-60: channel 1
    (61, 1), (90, 1),                # days 61-90: channel 2
    (181, 5), (210, 5),              # days 181-210: channel 6
    (211, 0), (241, 1),              # after channel 6, channel 1 again
])
def test_rotation_boundaries_with_six_channels(day, expected):
    assert gate.channel_index_for(day - 1, 6) == expected


def test_each_user_rotates_on_their_own_clock_with_days_left(three):
    started_days_ago(1, 5)
    started_days_ago(2, 30)
    started_days_ago(3, 65)
    started_days_ago(4, 125)                      # day 126: period 4 -> channel 1 again
    assert gate.position(1) is None
    p2, p3, p4 = gate.position(2), gate.position(3), gate.position(4)
    assert (p2.period, p2.channel.chat_id, p2.days_left) == (1, ONE, 30)
    assert (p3.period, p3.channel.chat_id, p3.days_left) == (2, TWO, 25)
    assert (p4.period, p4.channel.chat_id) == (4, ONE)


# --- 2. membership check -----------------------------------------------------------------------------
@pytest.mark.parametrize("status,is_member,joined", [
    ("creator", True, True),            # the owner
    ("administrator", True, True),
    ("member", True, True),
    ("restricted", True, True),         # restricted but still in the channel
    ("restricted", False, False),
    ("left", False, False),
    ("kicked", False, False),
])
def test_member_statuses(three, status, is_member, joined):
    started_days_ago(5, 35)

    async def scenario():
        async with Harness() as h:
            h.request.member_status, h.request.member_is_member = status, is_member
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5, live=True) is joined
            assert h.request.member_chats == [str(ONE)]           # by numeric id

    run(scenario())


def test_positive_cached_15_minutes_negative_never_and_ive_joined_checks_live(three):
    started_days_ago(UID, 35)

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            h.request.member_status = "left"
            await membership.is_subscribed(ctx, UID)
            await membership.is_subscribed(ctx, UID)
            assert h.request.member_checks == 2                  # "not a member" is never cached
            h.request.member_status = "member"
            await membership.is_subscribed(ctx, UID)
            await membership.is_subscribed(ctx, UID)
            assert h.request.member_checks == 3                  # "member" is cached
            await h.tap("recheck_sub")
            assert h.request.member_checks == 4                  # ✅ I've joined always asks Telegram

    run(scenario())


def test_an_error_uses_the_last_known_result_and_never_blocks(three):
    started_days_ago(5, 35)

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            h.request.member_error = True
            assert await membership.is_subscribed(ctx, 5) is True         # nothing known: not blocked
            h.request.member_error, h.request.member_status = False, "left"
            assert await membership.is_subscribed(ctx, 5) is False
            h.request.member_error = True
            assert await membership.is_subscribed(ctx, 5) is False        # last known: not a member

    run(scenario())


@pytest.mark.parametrize("error", ["Bad Request: member list is inaccessible", "Bad Request: chat not found"])
def test_a_channel_the_bot_cant_check_lets_users_through_and_alerts(three, monkeypatch, error):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    started_days_ago(5, 35)

    async def scenario():
        async with Harness() as h:
            h.request.member_error, h.request.member_error_text = True, error
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5) is True
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == ADMIN]
            assert len(alerts) == 1 and str(ONE) in alerts[0]

    run(scenario())


# --- 4. staying in the channel --------------------------------------------------------------------------
def test_leaving_the_current_channel_blocks_the_next_action(three):
    started_days_ago(UID, 35)                                  # channel 1, 25 days left

    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)                     # a member: in
            assert "No transactions yet" in out.texts[0]
            assert membership.membership_cache.fresh((UID, ONE))

            h.request.member_status = "left"
            await h.channel_member(ONE, UID, "member", "left")  # Telegram tells the bot
            assert not membership.membership_cache.fresh((UID, ONE))   # cache cleared at once

            out = await h.text(BTN_HISTORY)
            assert f"You left Title of {ONE}" in out.texts[0] and "Rejoin to keep using the bot" in out.texts[0]
            assert "25 more day(s)" in out.texts[0]
            assert out.buttons()[0] == {"text": f"📢 Join Title of {ONE}", "url": LINKS[ONE]}

            h.request.member_status = "member"
            out = await h.tap("recheck_sub")
            assert "You're in" in out.texts[0]

    run(scenario())
    assert [e for _, _, e in events(UID)] == ["already_member", "left", "shown", "rejoined"]


def test_leaving_an_earlier_periods_channel_changes_nothing(three):
    started_days_ago(UID, 65)                                  # period 2: channel 2

    async def scenario():
        async with Harness() as h:
            h.request.statuses[(str(ONE), UID)] = "left"       # not in channel 1 any more
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0]
            await h.channel_member(ONE, UID, "member", "left")
            assert membership.membership_cache.fresh((UID, TWO))      # untouched
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0]
            assert h.request.member_chats == [str(TWO)]         # channel 1 is never checked again

    run(scenario())
    assert events(UID) == [(TWO, 2, "already_member")]         # the leave from channel 1 isn't counted


def test_never_interrupted_mid_entry_and_data_untouched(three):
    from app.services import transactions
    started_days_ago(UID, 35)

    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            h.request.member_status = "left"
            await h.channel_member(ONE, UID, "member", "left")  # leaves halfway
            await h.text("25")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            out = await h.tap("skip_note")
            assert "Logged" in out.texts[-1]
            out = await h.text(BTN_HISTORY)                     # the next action is stopped
            assert "You left" in out.texts[0]
            assert len(transactions.list_recent(UID)) == 1       # and nothing was removed

    run(scenario())


def test_a_channel_member_who_never_used_the_bot_is_ignored(three):
    async def scenario():
        async with Harness() as h:
            await h.channel_member(ONE, 4242, "member", "left")

    run(scenario())
    assert users.is_active(4242) is False and events() == []


# --- 5. join screen and invite links ------------------------------------------------------------------------
def test_join_screen_names_the_channel_and_the_days_left(three):
    started_days_ago(UID, 40)                                  # channel 1, 20 days left

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            text = out.texts[0]
            assert f"This period's channel: Title of {ONE}" in text and "next 20 day(s)" in text
            join, joined = out.buttons()
            assert join == {"text": f"📢 Join Title of {ONE}", "url": LINKS[ONE]}
            assert joined == {"text": "✅ I've joined", "callback_data": "recheck_sub"}

    run(scenario())


def test_gate_on_makes_one_finance_bot_link_per_channel_and_reuses_it(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)

    async def scenario():
        async with Harness() as h:
            await membership.startup_check(h.app.bot)          # gate off: no links made
            assert h.request.invite_links == 0
            await admin_says(h, "/gate_on")
            created = [p for e, p in h.request.calls if e == "createChatInviteLink"]
            assert len(created) == 6 and {p["name"] for p in created} == {"Finance Bot"}
            stored = [c.invite_link for c in gate.channels()]
            assert all(stored)

            await admin_says(h, "/gate_on")                     # again: the same links are kept
            assert h.request.invite_links == 6 and [c.invite_link for c in gate.channels()] == stored

            h.request.revoked.add(stored[2])                    # one gets revoked
            await membership.startup_check(h.app.bot)
            after = [c.invite_link for c in gate.channels()]
            assert h.request.invite_links == 7 and after[2] != stored[2] and after[:2] == stored[:2]

    run(scenario())


def test_without_the_invite_right_no_join_button_and_an_alert(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    started_days_ago(UID, 35)
    gate.store_invite_link(ONE, None)

    async def scenario():
        async with Harness() as h:
            h.request.no_invite_in = {str(ONE)}
            out = await admin_says(h, "/gate_on")
            assert any(f"<code>{ONE}</code>) · bot admin ✅ · invite link ❌" in x for x in out.texts)
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and "Invite users via link" in p["text"]]
            assert len(alerts) == 1 and str(ONE) in alerts[0]

            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "This period's channel" in out.texts[0]
            assert [b["text"] for b in out.buttons()] == ["✅ I've joined"]

    run(scenario())


def test_startup_with_the_gate_on_alerts_about_each_problem(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)

    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {str(ONE), str(TWO)}
            h.request.no_invite_in = {str(TWO)}
            gate.store_invite_link(TWO, None)
            await membership.startup_check(h.app.bot)
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == ADMIN]
            assert any("isn't an administrator" in a and str(THREE) in a for a in alerts)
            assert any("Invite users via link" in a and str(TWO) in a for a in alerts)

    run(scenario())


# --- 6. counting ----------------------------------------------------------------------------------------
def test_counting_rules_and_gate_status(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    for uid in (11, 12, 13):
        started_days_ago(uid, 35)                              # all on channel 1
    started_days_ago(14, 10)                                     # free
    started_days_ago(15, 65)                                     # on channel 2

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            h.request.statuses = {(str(ONE), 11): "left", (str(ONE), 12): "member", (str(ONE), 13): "left",
                                  (str(TWO), 15): "member"}
            for uid in (11, 12, 13, 15):
                if not await membership.is_subscribed(ctx, uid):
                    await membership.join_screen(h.app.bot, uid, gate.position(uid))   # shown
            await h.channel_member(ONE, 11, "left", "member")    # 11 joins via the bot
            await h.channel_member(ONE, 13, "left", "member")    # 13 joins via the bot...
            await h.channel_member(ONE, 13, "member", "left")    # ...leaves...
            await h.channel_member(ONE, 13, "left", "member")    # ...and comes back
            await h.channel_member(ONE, 12, "member", "left")    # 12 (already a member) leaves
            await h.channel_member(TWO, 11, "member", "left")    # not 11's channel: not counted
            out = await admin_says(h, "/gate_status")
            return out.texts[0]

    text = run(scenario())
    one = gate.stats()["channels"][0]
    assert {k: one[k] for k in ("required", "shown", "joined_via_bot", "already_member", "left", "rejoined",
                                "subscribed")} == {"required": 3, "shown": 2, "joined_via_bot": 2,
                                                   "already_member": 1, "left": 2, "rejoined": 1, "subscribed": 2}
    two = gate.stats()["channels"][1]
    assert (two["required"], two["already_member"], two["left"], two["subscribed"]) == (1, 1, 0, 1)
    assert "Channel gate</b>: on" in text and f"1. Title of {ONE}" in text
    assert ("required now 3 · shown 2 · joined via bot 2 · already members 1 · left 2 · rejoined 1 · "
            "subscribed now 2") in text
    assert "free first 30 days: 1 user(s)" in text


def test_gate_stats_counts_only_the_last_n_days(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    started_days_ago(1, 35)
    old = (datetime.now(timezone.utc) - timedelta(days=20)).replace(tzinfo=None).isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO gate_events (user_id, channel_id, period_number, event, at) "
                     "VALUES (1, ?, 1, 'joined_via_bot', ?)", (ONE, old))
        conn.execute("INSERT INTO gate_events (user_id, channel_id, period_number, event, at) "
                     "VALUES (2, ?, 1, 'joined_via_bot', datetime('now'))", (ONE,))

    async def scenario():
        async with Harness() as h:
            week = (await admin_says(h, "/gate_stats 7")).texts[0]
            month = (await admin_says(h, "/gate_stats 30")).texts[0]
            how = (await admin_says(h, "/gate_stats")).texts[0]
            return week, month, how

    week, month, how = run(scenario())
    assert "last 7 day(s)" in week and "joined via bot 1 ·" in week
    assert "last 30 day(s)" in month and "joined via bot 2 ·" in month
    assert "/gate_stats 30" in how


# --- the Mini App ---------------------------------------------------------------------------------------
def test_mini_app_gets_a_403_with_the_channel_link_and_days_left(three, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    harness = Harness()
    started_days_ago(8, 65)                                     # channel 2, 25 days left

    def get(uid):
        return client.get("/api/me", headers={"Authorization": "tma " + make_init_data({"id": uid}, config.BOT_TOKEN)})

    with TestClient(create_app(application=harness.app)) as client:
        harness.request.member_status = "left"
        assert get(7).status_code == 200                        # first visit: free days
        r = get(8)
        assert r.status_code == 403
        assert r.json()["detail"] == {"error": "not_subscribed", "channel": f"Title of {TWO}",
                                      "join_link": LINKS[TWO], "left": False, "days_left": 25}


# --- admin commands ---------------------------------------------------------------------------------------
@pytest.fixture
def admin(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)


def test_gate_add_from_a_forwarded_post(admin):
    async def scenario():
        async with Harness() as h:
            new = -1004444444444
            out = await admin_says(h, "/gate_add", forwarded_from=new)
            assert f"Added Title of {new}" in out.texts[0] and "as channel 4" in out.texts[0]
            assert gate.channels()[-1].chat_id == new and gate.channels()[-1].invite_link   # gate is on: link made
            assert "already in the rotation" in (await admin_says(h, "/gate_add", forwarded_from=new)).texts[0]
            h.request.bot_admin_in = set()
            assert "not an administrator" in (await admin_says(h, "/gate_add", forwarded_from=-1005555555555)).texts[0]
            assert "Forward any post" in (await admin_says(h, "/gate_add")).texts[0]
            assert "numeric id" in (await admin_says(h, "/gate_add @channel")).texts[0]

    run(scenario())


def test_gate_remove_list_on_off(admin):
    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {str(ONE), str(THREE)}
            text = (await admin_says(h, "/gate_list")).texts[0]
            assert f"1. Title of {ONE} (<code>{ONE}</code>) · bot admin ✅ · invite link ✅" in text
            assert f"2. Title of {TWO} (<code>{TWO}</code>) · bot admin ❌ · invite link ❌" in text
            text = (await admin_says(h, "/gate_remove 2")).texts[0]
            assert f"Removed Title of {TWO}" in text and f"2. Title of {THREE}" in text
            assert "number from /gate_list" in (await admin_says(h, "/gate_remove")).texts[0]
            assert "off" in (await admin_says(h, "/gate_off")).texts[0] and gate.is_on() is False
            assert "on" in (await admin_says(h, "/gate_on")).texts[0] and gate.is_on() is True

    run(scenario())


def test_gate_commands_are_admin_only(admin):
    async def scenario():
        async with Harness() as h:
            for command in ("/gate_list", "/gate_on", "/gate_off", "/gate_remove 1", "/gate_status", "/gate_stats 7",
                            "/gate_add -1007777777777"):
                assert await admin_says(h, command, user_id=UID) == [], command
            assert len(gate.channels()) == 3 and gate.is_on()

    run(scenario())
