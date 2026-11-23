"""Phase 4.11: better recaps (weekly comparison and top category, monthly recap, switches)."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.db import get_conn, init_db
from app.services import periods, prefs, recap, transactions, users
from tests.fake_telegram import UID, Harness, run

WEDNESDAY = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
DEC_2 = datetime(2026, 12, 2, 9, tzinfo=timezone.utc)


def dated(user_id, amount, category, day, type_="expense"):
    entry, _ = transactions.add_entry(user_id, amount * 100, type_, category, "cash", "", None)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", (f"{day}T09:00:00", entry["id"]))


@pytest.fixture
def db(fresh_db):
    init_db()
    users.register_user(UID)
    # the week before last (9-15 Nov) and last week (16-22 Nov)
    dated(UID, 100, "food", "2026-11-10")
    dated(UID, 1000, "salary", "2026-11-10", "income")
    dated(UID, 90, "food", "2026-11-17")
    dated(UID, 60, "transport", "2026-11-18")
    dated(UID, 1500, "salary", "2026-11-19", "income")
    # October, for the monthly comparison
    dated(UID, 200, "food", "2026-10-05")




def test_weekly_text(db):
    start, end = periods.previous_week(WEDNESDAY)
    text = recap.recap_text(UID, start, end)
    assert "Expenses: KES 150 (↑ 50% vs the week before)" in text      # 150 vs 100
    assert "Income: KES 1,500 (↑ 50% vs the week before)" in text
    assert "🏆 Top category: 🍔 Food, KES 90 (60% of spending)" in text


def test_no_comparison_when_the_week_before_was_empty(fresh_db):
    init_db()
    dated(UID, 40, "fun", "2026-11-18")
    start, end = periods.previous_week(WEDNESDAY)
    text = recap.recap_text(UID, start, end)
    assert "Expenses: KES 40\n" in text and "vs the week before" not in text
    assert "All categories" not in text                                   # one category: just the top line


def test_monthly_text(db):
    start, end = periods.previous_month(DEC_2)
    text = recap.recap_text(UID, start, end, "monthly")
    assert text.startswith("🗓️ <b>Your November recap</b>")
    assert "Expenses: KES 250 (↑ 25% vs the month before)" in text      # 250 vs 200 in October
    assert "🏆 Top category: 🍔 Food, KES 190 (76% of spending)" in text


def test_monthly_recap_sends_once_and_respects_its_switch(db):
    users.register_user(7)
    dated(7, 10, "food", "2026-11-03")
    prefs.set_prefs(7, monthly_recap_enabled=False)

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot)
            stats = await recap.run_recap(ctx, now=DEC_2, rate=1000, kind="monthly")
            assert stats["sent"] == 1 and h.request.delivered == [UID]
            again = await recap.run_recap(ctx, now=DEC_2, rate=1000, kind="monthly")
            assert again["sent"] == 0                                    # restart-safe
            weekly = await recap.run_recap(ctx, now=WEDNESDAY, rate=1000)  # separate marker
            assert weekly["sent"] == 1

    run(scenario())


def test_weekly_switch_does_not_affect_monthly(db):
    prefs.set_prefs(UID, recap_enabled=False)
    assert users.recap_candidates("2026-11-16", "weekly") == []
    assert users.recap_candidates("2026-11-01", "monthly") == [UID]


def test_monthly_job_runs_on_the_1st_at_0800(db):
    from zoneinfo import ZoneInfo

    from app import config

    async def scenario():
        async with Harness() as h:
            job = next(j for j in h.app.job_queue.jobs() if j.name == "monthly_recap")
            t = job.next_t.astimezone(ZoneInfo(config.APP_TIMEZONE))
            assert (t.day, t.strftime("%H:%M")) == (1, "08:00")

    run(scenario())


def test_bot_switches(db):
    async def scenario():
        async with Harness() as h:
            out = await h.tap("set:mrecap")
            assert "Monthly recap (the 1st): <b>off</b>" in out.texts[-1]
            assert prefs.get_prefs(UID) == {"currency": "KES", "recap_enabled": True, "monthly_recap_enabled": False}
            await h.tap("set:recap")
            assert prefs.get_prefs(UID)["recap_enabled"] is False

    run(scenario())


def test_admin_preview_of_the_monthly_recap(db, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)

    async def scenario():
        async with Harness() as h:
            out = await h.text("/recap_now month")
            assert out.texts and ("recap" in out.texts[0].lower())

    run(scenario())
