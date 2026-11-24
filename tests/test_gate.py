"""The channel gate: in the database by numeric id, off until /gate_on, and ONE
schedule shared by every user (no free period): each 30-day period has one
channel, starting from the start channel and going round the list. Users must
stay in the current channel; one stored invite link per channel; events counted
per channel and global period."""
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

EARN, NOTEBOOK, WTAL, ALPHA, HUSTLE, WALL = (-1002704031424, -1002905948541, -1004376927203, -1001992993907,
                                             -1001897854375, -1001200205264)
SEEDED = [EARN, NOTEBOOK, WTAL, ALPHA, HUSTLE, WALL]
START = datetime(2026, 11, 23, 21, tzinfo=timezone.utc)   # 24 Nov 2026 00:00 in Nairobi
ONE, TWO, THREE = -1001111111111, -1002222222222, -1003333333333
LINKS = {ONE: "https://t.me/+one", TWO: "https://t.me/+two", THREE: "https://t.me/+three"}
ADMIN = 999


@pytest.fixture
def db(fresh_db, monkeypatch):
    init_db()
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)


def schedule(days_in: float, start_channel=ONE):
    """Start the shared schedule so that right now is `days_in` days after its start."""
    gate.set_schedule(datetime.now(timezone.utc) - timedelta(days=days_in), start_channel)


@pytest.fixture
def three(db):
    """The gate on, with three channels of our own (each with its invite link),
    and the schedule 5 days into period 0 (channel ONE, 25 days left)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM gate_channels")
    for chat_id in (ONE, TWO, THREE):
        gate.add_channel(chat_id)
        gate.store_invite_link(chat_id, LINKS[chat_id])
    schedule(5)
    gate.set_on(True)


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


# --- stored setup ---------------------------------------------------------------------------------------
def test_the_six_channels_and_the_schedule_are_stored_and_the_gate_is_off(db):
    assert [c.chat_id for c in gate.channels()] == SEEDED
    assert gate.schedule_start() == (START, WTAL)
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
    assert not hasattr(gate, "FREE_DAYS")


def test_the_webhook_asks_for_chat_member_updates():
    from telegram import Update
    assert "chat_member" in Update.ALL_TYPES   # what start_bot passes as allowed_updates


# --- the shared schedule ---------------------------------------------------------------------------------
@pytest.mark.parametrize("after,period,channel", [
    (timedelta(0), 0, WTAL),                              # day 1: We Talk A Lot
    (timedelta(days=29, hours=23), 0, WTAL),              # day 30: still period 0
    (timedelta(days=30), 1, ALPHA),                       # day 31: Crypto Alpha Edge US
    (timedelta(days=59, hours=23), 1, ALPHA),             # day 60
    (timedelta(days=60), 2, HUSTLE),                      # day 61: Hustle To Millions
    (timedelta(days=90), 3, WALL),                        # Crypto Wall Street
    (timedelta(days=120), 4, EARN),                       # Earn Stack
    (timedelta(days=150), 5, NOTEBOOK),                   # Crypto Notebook: the 6th
    (timedelta(days=180), 6, WTAL),                       # after the 6th: We Talk A Lot again
    (timedelta(days=210), 7, ALPHA),
])
def test_period_boundaries_and_wrap(db, after, period, channel):
    pos = gate.current(START + after)
    assert (pos.period, pos.channel.chat_id) == (period, channel)
    assert pos.starts_at == START + timedelta(days=30 * period)
    assert pos.ends_at == pos.starts_at + timedelta(days=30)


def test_days_left_and_next_channel(db):
    pos = gate.current(START + timedelta(hours=12))
    assert (pos.days_left, pos.next_channel.chat_id) == (30, ALPHA)
    pos = gate.current(START + timedelta(days=29, hours=12))
    assert (pos.days_left, pos.next_channel.chat_id) == (1, ALPHA)
    pos = gate.current(START + timedelta(days=150, hours=1))
    assert pos.next_channel.chat_id == WTAL


def test_upcoming_lists_the_next_six_periods(db):
    got = [(p.period, p.channel.chat_id) for p in gate.upcoming(6, START + timedelta(days=31))]
    assert got == [(1, ALPHA), (2, HUSTLE), (3, WALL), (4, EARN), (5, NOTEBOOK), (6, WTAL)]


def test_everyone_old_or_new_has_the_same_channel_now(three):
    for uid in (1, 2, 3):
        users.register_user(uid)
    with get_conn() as conn:   # 2 has been around for months, 3 arrived today
        conn.execute("UPDATE users SET first_start_at = '2025-01-01T00:00:00' WHERE user_id = 2")
    assert {gate.position(uid).channel.chat_id for uid in (1, 2, 3, 777)} == {ONE}


def test_a_new_user_needs_the_current_channel_at_once(three):
    schedule(35)                                                # period 1: channel TWO

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)                     # their very first action
            assert f"This period's channel: Title of {TWO} — 25 days left" in out.texts[0]

    run(scenario())


def test_the_admin_is_exempt(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)

    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0] and h.request.member_checks == 0

    run(scenario())


# --- membership check -------------------------------------------------------------------------------------
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
    async def scenario():
        async with Harness() as h:
            h.request.member_status, h.request.member_is_member = status, is_member
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5, live=True) is joined
            assert h.request.member_chats == [str(ONE)]           # by numeric id

    run(scenario())


def test_positive_cached_15_minutes_negative_never_and_ive_joined_checks_live(three):
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

    async def scenario():
        async with Harness() as h:
            h.request.member_error, h.request.member_error_text = True, error
            assert await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), 5) is True
            alerts = [p["text"] for e, p in h.request.sent if e == "sendMessage" and int(p["chat_id"]) == ADMIN]
            assert len(alerts) == 1 and str(ONE) in alerts[0]

    run(scenario())


# --- staying in the channel -----------------------------------------------------------------------------------
def test_leaving_the_current_channel_blocks_the_next_action(three):
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
            assert "— 25 days left" in out.texts[0]
            assert out.buttons()[0] == {"text": f"📢 Join Title of {ONE}", "url": LINKS[ONE]}

            h.request.member_status = "member"
            out = await h.tap("recheck_sub")
            assert "You're in" in out.texts[0]

    run(scenario())
    assert events(UID) == [(ONE, 0, "already_member"), (ONE, 0, "left"), (ONE, 0, "shown"), (ONE, 0, "rejoined")]


def test_leaving_an_earlier_periods_channel_changes_nothing(three):
    schedule(35)                                                # period 1: channel TWO

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
    assert events(UID) == [(TWO, 1, "already_member")]         # the global period; ONE's leave not counted


def test_never_interrupted_mid_entry_and_data_untouched(three):
    from app.services import transactions

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


# --- join screen and invite links ------------------------------------------------------------------------------
def test_join_screen_names_the_channel_and_the_days_left(three):
    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            out = await h.text(BTN_HISTORY)
            assert f"This period's channel: Title of {ONE} — 25 days left" in out.texts[0]
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


# --- counting -----------------------------------------------------------------------------------------------
def test_counting_rules_and_gate_status(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    for uid in (11, 12, 13, 14):
        users.register_user(uid)

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            h.request.statuses = {(str(ONE), 11): "left", (str(ONE), 12): "member", (str(ONE), 13): "left",
                                  (str(ONE), 14): "member"}
            for uid in (11, 12, 13):
                if not await membership.is_subscribed(ctx, uid):
                    await membership.join_screen(h.app.bot, uid, gate.position(uid))   # shown
            await h.channel_member(ONE, 11, "left", "member")    # 11 joins via the bot
            await h.channel_member(ONE, 13, "left", "member")    # 13 joins via the bot...
            await h.channel_member(ONE, 13, "member", "left")    # ...leaves...
            await h.channel_member(ONE, 13, "left", "member")    # ...and comes back
            await h.channel_member(ONE, 12, "member", "left")    # 12 (already a member) leaves
            await h.channel_member(TWO, 11, "member", "left")    # not the current channel: not counted
            await h.channel_member(ONE, 14, "member", "left")    # 14 was never checked: nothing to count
            return (await admin_says(h, "/gate_status")).texts[0]

    text = run(scenario())
    one, two, _ = gate.stats()["channels"]
    assert {k: one[k] for k in ("required", "shown", "joined_via_bot", "already_member", "left", "rejoined",
                                "subscribed")} == {"required": 4, "shown": 2, "joined_via_bot": 2,
                                                   "already_member": 1, "left": 2, "rejoined": 1, "subscribed": 2}
    assert all(two[k] == 0 for k in ("required", "left", "subscribed"))
    assert {p for _, p, _ in events()} == {0}                 # all in global period 0
    assert "Channel gate</b>: on" in text and f"<b>Now:</b> Title of {ONE} · period 0" in text
    assert f"<b>Next:</b> Title of {TWO}" in text and "25 days left" in text
    assert ("required now 4 · shown 2 · joined via bot 2 · already members 1 · left 2 · rejoined 1 · "
            "subscribed now 2") in text


def test_gate_stats_counts_only_the_last_n_days(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)
    old = (datetime.now(timezone.utc) - timedelta(days=20)).replace(tzinfo=None).isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO gate_events (user_id, channel_id, period_number, event, at) "
                     "VALUES (1, ?, 0, 'joined_via_bot', ?)", (ONE, old))
        conn.execute("INSERT INTO gate_events (user_id, channel_id, period_number, event, at) "
                     "VALUES (2, ?, 0, 'joined_via_bot', datetime('now'))", (ONE,))

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


# --- the Mini App ------------------------------------------------------------------------------------------
def test_mini_app_gets_a_403_with_the_channel_link_and_days_left(three, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    harness = Harness()
    schedule(35)                                                # channel TWO, 25 days left

    with TestClient(create_app(application=harness.app)) as client:
        harness.request.member_status = "left"
        r = client.get("/api/me", headers={"Authorization": "tma " + make_init_data({"id": 8}, config.BOT_TOKEN)})
        assert r.status_code == 403                             # a brand-new user: no free period
        assert r.json()["detail"] == {"error": "not_subscribed", "channel": f"Title of {TWO}",
                                      "join_link": LINKS[TWO], "left": False, "days_left": 25}


# --- admin commands -------------------------------------------------------------------------------------
@pytest.fixture
def admin(three, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", ADMIN)


def test_gate_schedule_lists_the_next_six_periods(admin):
    schedule(31)                                                # period 1: TWO

    async def scenario():
        async with Harness() as h:
            return (await admin_says(h, "/gate_schedule")).texts[0]

    text = run(scenario())
    lines = [line for line in text.splitlines() if line[:2] in {f"{n}." for n in range(1, 7)}]
    assert [line.split(":")[0] for line in lines] == [
        f"1. Title of {TWO}", f"2. Title of {THREE}", f"3. Title of {ONE}", f"4. Title of {TWO}",
        f"5. Title of {THREE}", f"6. Title of {ONE}"]
    assert "← now, 29 days left" in lines[0] and "now" not in lines[1]


def test_gate_list_shows_the_current_period(admin):
    async def scenario():
        async with Harness() as h:
            h.request.bot_admin_in = {str(ONE), str(THREE)}
            return (await admin_says(h, "/gate_list")).texts[0]

    text = run(scenario())
    assert f"<b>Now:</b> Title of {ONE} · period 0" in text and "25 days left" in text
    assert f"<b>Next:</b> Title of {TWO}" in text
    assert f"1. Title of {ONE} (<code>{ONE}</code>) · bot admin ✅ · invite link ✅" in text
    assert f"2. Title of {TWO} (<code>{TWO}</code>) · bot admin ❌ · invite link ❌" in text


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


def test_gate_remove_on_off(admin):
    async def scenario():
        async with Harness() as h:
            text = (await admin_says(h, "/gate_remove 2")).texts[0]
            assert f"Removed Title of {TWO}" in text and f"2. Title of {THREE}" in text
            assert "number from /gate_list" in (await admin_says(h, "/gate_remove")).texts[0]
            assert "off" in (await admin_says(h, "/gate_off")).texts[0] and gate.is_on() is False
            out = await admin_says(h, "/gate_on")
            assert "on" in out.texts[0] and "<b>Now:</b>" in out.texts[0] and gate.is_on() is True

    run(scenario())


def test_gate_commands_are_admin_only(admin):
    async def scenario():
        async with Harness() as h:
            for command in ("/gate_list", "/gate_on", "/gate_off", "/gate_remove 1", "/gate_status", "/gate_stats 7",
                            "/gate_schedule", "/gate_add -1007777777777"):
                assert await admin_says(h, command, user_id=UID) == [], command
            assert len(gate.channels()) == 3 and gate.is_on()

    run(scenario())
