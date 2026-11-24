"""Worldwide users: each picks a currency and timezone at first start, and weeks,
months, budgets, recaps and recurring entries follow their own clock."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_ADD, BTN_HISTORY, BTN_SETTINGS
from app.db import get_conn, init_db
from app.services import accounts, budgets, periods, prefs, recap, recurring, summaries, timezones, transactions, users
from tests.fake_telegram import UID, Harness, run

UTC = timezone.utc
TOKYO, NEW_YORK = "Asia/Tokyo", "America/New_York"   # UTC+9 and UTC-5 in November


@pytest.fixture
def db(fresh_db):
    init_db()


def at(user_id, amount, stored_utc, category="food", type_="expense"):
    """An entry whose occurred_at is exactly `stored_utc` (naive UTC text)."""
    entry, _ = transactions.add_entry(user_id, amount * 100, type_, category, "cash", "", None)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", (stored_utc, entry["id"]))


# --- first start ------------------------------------------------------------------------
def test_first_start_asks_currency_then_timezone(db):
    async def scenario():
        async with Harness(setup=None) as h:
            out = await h.text("/start")
            assert "Which currency" in out.texts[0]
            assert {"ob:cur:USD", "ob:cur:EUR", "ob:cur:INR", "ob:cur:other"} <= {b["callback_data"] for b in out.buttons()}

            out = await h.tap("ob:cur:EUR")
            assert "Currency: <b>EUR</b>" in out.texts[0] and "EUR 1,500" in out.texts[0]
            assert "What's your timezone" in out.texts[1]
            assert any(b.get("request_location") for b in out.buttons(1))       # 📍 Share my location
            assert any(b["callback_data"] == "tz:r:europe" for b in out.buttons())

            out = await h.tap("tz:r:europe")
            assert any(b["callback_data"] == "tz:z:Europe/Berlin" and "Berlin · UTC+1" in b["text"] for b in out.buttons())
            out = await h.tap("tz:z:Europe/Berlin")
            assert "Timezone: <b>Europe/Berlin</b>" in out.texts[0]
            assert "All set" in out.texts[1] and "Welcome" in out.texts[2]

            assert prefs.get_prefs(UID) == {"currency": "EUR", "timezone": "Europe/Berlin", "recap_enabled": True,
                                            "monthly_recap_enabled": True, "onboarded": True}
            assert [k for k, _ in accounts.choices(UID)] == ["cash", "bank", "card", "mobile_money"]

            out = await h.text("500 food lunch")                       # now everything works
            assert "Logged −EUR 500" in out.texts[0]

    run(scenario())


def test_nothing_works_until_setup_is_done(db):
    async def scenario():
        async with Harness(setup=None) as h:
            out = await h.text(BTN_HISTORY)
            assert "Which currency" in out.texts[0]
            out = await h.text("500 food lunch")
            assert "3-letter" in out.texts[0]                      # taken as a (bad) currency answer
            assert transactions.list_recent(UID) == []

    run(scenario())


def test_other_currency_and_a_typed_city(db):
    async def scenario():
        async with Harness(setup=None) as h:
            await h.text("/start")
            out = await h.tap("ob:cur:other")
            assert "3-letter" in out.texts[0]
            out = await h.text("mwk")
            assert "Currency: <b>MWK</b>" in out.texts[0]
            out = await h.text("Atlantis")
            assert "couldn't find" in out.texts[0]
            out = await h.text("new york")
            assert "America/New_York" in out.texts[0] and "UTC-5" in out.texts[0]
            assert prefs.get_prefs(UID)["timezone"] == NEW_YORK

    run(scenario())


def test_a_typed_offset_is_a_fixed_zone(db):
    async def scenario():
        async with Harness(setup=None) as h:
            await h.text("/start")
            await h.tap("ob:cur:USD")
            out = await h.text("UTC+3")
            assert "no daylight saving" in out.texts[0]
            assert prefs.get_prefs(UID)["timezone"] == "Etc/GMT-3"   # POSIX sign: GMT-3 is UTC+3

    run(scenario())


def test_shared_location_picks_the_zone(db):
    async def scenario():
        async with Harness(setup=None) as h:
            await h.text("/start")
            await h.tap("ob:cur:INR")
            out = await h.location(28.61, 77.21)                     # New Delhi
            assert "Asia/Kolkata" in out.texts[0] and "UTC+5:30" in out.texts[0]
            assert prefs.get_prefs(UID)["onboarded"]

    run(scenario())


def test_a_restart_mid_setup_asks_the_missing_question(db):
    async def scenario():
        async with Harness(setup=None) as h:
            await h.text("/start")
            await h.tap("ob:cur:GBP")
            h.app.user_data[UID].clear()                              # the bot restarted: questions forgotten
            out = await h.text(BTN_HISTORY)
            assert "What's your timezone" in out.texts[0]

    run(scenario())


def test_change_timezone_in_settings(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_SETTINGS)
            assert "Timezone: <b>Africa/Nairobi</b>" in out.texts[0]
            out = await h.tap("tz:settings")
            assert any("What's your timezone" in x for x in out.texts)
            await h.tap("tz:r:asia")
            out = await h.tap(f"tz:z:{TOKYO}")
            assert "Timezone: <b>Asia/Tokyo</b>" in out.texts[-1]          # the settings screen again
            assert prefs.get_prefs(UID)["timezone"] == TOKYO

            await h.tap("tz:settings")
            out = await h.text(BTN_HISTORY)                              # moving on drops the question
            assert "No transactions yet" in out.texts[0]

    run(scenario())


def test_timezone_parsing():
    assert timezones.parse("Berlin") == "Europe/Berlin"
    assert timezones.parse("sao paulo") == "America/Sao_Paulo"
    assert timezones.parse("Mumbai") == "Asia/Kolkata"
    assert timezones.parse("gmt-5") == "Etc/GMT+5"
    assert timezones.parse("+5:30") == "Asia/Kolkata"
    assert timezones.parse("UTC") == "UTC"
    assert timezones.parse("UTC+15") is None and timezones.parse("") is None
    assert all(timezones.is_valid(z) for zones in timezones.REGIONS.values() for z in zones)
    assert timezones.from_location(-1.29, 36.82) == "Africa/Nairobi"
    assert timezones.from_location(40.71, -74.0) == NEW_YORK


# --- weeks and months follow the user's clock -----------------------------------------------
def test_the_same_moment_is_a_different_week_for_different_users(db):
    """Sunday 29 Nov 2026, 20:00 UTC is already Monday in Tokyo but still Sunday in New York."""
    prefs.set_prefs(1, "JPY", timezone=TOKYO)
    prefs.set_prefs(2, "USD", timezone=NEW_YORK)
    for uid in (1, 2):
        at(uid, 10, "2026-11-29T20:00:00")
    monday_tokyo = datetime(2026, 11, 30, 1, tzinfo=UTC)   # Mon 10:00 Tokyo, Sun 20:00 New York
    assert summaries.summary(1, "week", now=monday_tokyo)["expense_minor"] == 1000   # Tokyo: this week
    assert summaries.summary(2, "week", now=monday_tokyo)["expense_minor"] == 1000   # NY: still the old week
    tuesday = datetime(2026, 12, 1, 15, tzinfo=UTC)          # Tuesday everywhere
    assert summaries.summary(1, "week", now=tuesday)["expense_minor"] == 1000
    assert summaries.summary(2, "week", now=tuesday)["expense_minor"] == 0           # was last week in NY


def test_budget_month_follows_the_user(db):
    prefs.set_prefs(1, "JPY", timezone=TOKYO)
    budgets.set_budget(1, "food", 100)
    at(1, 90, "2026-11-30T16:00:00")                          # 1 Dec 01:00 in Tokyo: December
    december = datetime(2026, 12, 5, tzinfo=UTC)
    assert next(b for b in budgets.overview(1, december) if b["category"] == "food")["spent_minor"] == 9000
    assert budgets.warning_for(1, "food", december)["percent"] == 90


def test_recurring_waits_for_0600_where_the_user_is(db):
    prefs.set_prefs(1, "JPY", timezone=TOKYO)
    entry, _ = transactions.add_entry(1, 5000, "expense", "bills", "bank", "Gym", None)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = '2026-11-20T03:00:00' WHERE id = ?", (entry["id"],))
    rule = recurring.create_from_entry(1, entry["id"], "weekly")
    assert rule["next_date"] == "2026-11-27"
    assert recurring.process_due(now=datetime(2026, 11, 26, 20, 59, tzinfo=UTC)) == []   # 27 Nov 05:59 Tokyo
    created = recurring.process_due(now=datetime(2026, 11, 26, 21, 0, tzinfo=UTC))      # 06:00 Tokyo
    assert len(created) == 1
    with periods.use_zone(TOKYO):
        assert periods.local_date_of(transactions.get_entry(1, created[0][1])["occurred_at"]) == date(2026, 11, 27)


# --- the recap arrives at 08:00 local, hourly job -------------------------------------------
def test_recap_goes_out_at_0800_in_each_users_zone(db):
    prefs.set_prefs(1, "JPY", timezone=TOKYO)
    prefs.set_prefs(2, "USD", timezone=NEW_YORK)
    for uid in (1, 2):
        users.register_user(uid)
        at(uid, 25, "2026-11-18T12:00:00")                     # last week (16-22 Nov) for both

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            hour = datetime(2026, 11, 22, 22, tzinfo=UTC)       # Mon 07:00 Tokyo
            sent = {}
            for _ in range(24 * 2):                              # two days of hourly ticks
                for kind in ("weekly", "monthly"):
                    await recap.run_recap(ctx, now=hour, rate=1000, kind=kind)
                for uid in h.request.delivered:
                    sent.setdefault(uid, hour)
                hour += timedelta(hours=1)
            assert sent[1] == datetime(2026, 11, 22, 23, tzinfo=UTC)    # Mon 08:00 Tokyo
            assert sent[2] == datetime(2026, 11, 23, 13, tzinfo=UTC)    # Mon 08:00 New York
            assert sorted(h.request.delivered) == [1, 2]               # once each
            texts = [p["text"] for e, p in h.request.sent if e == "sendMessage"]
            assert any("JPY 25" in x for x in texts) and any("USD 25" in x for x in texts)

    run(scenario())


def test_a_recap_switched_on_mid_week_waits_for_next_monday(db):
    prefs.set_prefs(1, "USD", timezone=NEW_YORK)
    users.register_user(1)
    at(1, 25, "2026-11-18T12:00:00")
    with periods.use_zone(NEW_YORK):
        assert recap.due_key("weekly", datetime(2026, 11, 25, 15, tzinfo=UTC)) is None    # a Wednesday
    assert list(recap.due_users("weekly", datetime(2026, 11, 25, 15, tzinfo=UTC))) == []


def test_recap_tick_runs_both_kinds(db, monkeypatch):
    calls = []

    async def fake(context, now=None, rate=None, kind="weekly"):
        calls.append(kind)

    monkeypatch.setattr(recap, "run_recap", fake)
    run(recap.recap_tick(SimpleNamespace(bot=None)))
    assert calls == ["weekly", "monthly"]


# --- the Mini App --------------------------------------------------------------------------
def test_api_uses_the_users_zone_per_request(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    prefs.set_prefs(1, "JPY", timezone=TOKYO)
    prefs.set_prefs(2, "USD", timezone=NEW_YORK)

    def auth(uid):
        return {"Authorization": "tma " + make_init_data({"id": uid}, config.BOT_TOKEN)}

    with TestClient(create_app(application=Harness().app)) as client:
        tokyo = client.get("/api/summary?period=week", headers=auth(1)).json()
        new_york = client.get("/api/summary?period=week", headers=auth(2)).json()
        assert tokyo["from"].endswith("+09:00") and new_york["from"].endswith("-05:00")
        assert (tokyo["currency"], new_york["currency"]) == ("JPY", "USD")
        r = client.put("/api/settings", headers=auth(3), json={"currency": "EUR", "timezone": "Europe/Paris"})
        assert r.json()["settings"]["onboarded"] is True
        assert client.get("/api/summary?period=week", headers=auth(3)).json()["from"].endswith("+01:00")


def test_no_country_specific_defaults_left():
    assert not hasattr(config, "APP_TIMEZONE")
    assert not hasattr(config, "DEFAULT_CURRENCY")
    assert not hasattr(config, "DEFAULT_ACCOUNTS")
    assert periods.FALLBACK_ZONE == "UTC"
