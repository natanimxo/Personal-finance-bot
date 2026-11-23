"""One test (or more) per problem in Phase 1, step 2 of the upgrade plan."""
import asyncio
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import config
from app.bot.keyboards import BTN_ACCOUNTS, BTN_ADD, BTN_ADD_INCOME, BTN_CANCEL, BTN_HISTORY, BTN_SUMMARY, MINUS
from app.bot.membership import membership_cache
from app.db import get_conn, init_db
from app.services import accounts, periods, transactions
from app.services.recap import recap_text
from tests.fake_telegram import UID, Harness, assert_valid_html, run

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(fresh_db):
    init_db()
    return fresh_db


async def add_expense(h, amount="12.50", category="food", account="bank", note=None):
    await h.text(BTN_ADD)
    await h.text(amount)
    out = await h.tap(f"addcat_{category}")
    if account:
        out = await h.tap(f"addacc_{account}")
    return await (h.text(note) if note else h.tap("skip_note"))


# 1. Weekly recap -----------------------------------------------------------
def test_1_recap_runs_monday_0800_app_timezone(db):
    h = Harness()
    job = next(j for j in h.app.job_queue.jobs() if j.name == "weekly_recap")

    async def next_run():
        async with h:
            return job.next_t

    next_t = run(next_run()).astimezone(ZoneInfo(config.APP_TIMEZONE))
    assert next_t.strftime("%A %H:%M") == "Monday 08:00"


def test_1_recap_covers_last_monday_to_sunday(db):
    start, end = periods.previous_week(datetime(2026, 11, 25, 12, tzinfo=timezone.utc))
    for amount, created in [(10, "2026-11-15T20:59:00"),   # Sun 15 Nov 23:59 Nairobi: week before
                            (20, "2026-11-15T21:00:00"),   # Mon 16 Nov 00:00: in
                            (30, "2026-11-22T20:59:00"),   # Sun 22 Nov 23:59: in
                            (40, "2026-11-22T21:00:00")]:  # Mon 23 Nov 00:00: this week, out
        entry = transactions.add_expense(UID, amount, "food")
        with get_conn() as conn:
            conn.execute("UPDATE expenses SET created_at = ? WHERE id = ?", (created, entry))
    text = recap_text(UID, start, end)
    assert "Expenses: 50.00" in text and "Mon 16 Nov – Sun 22 Nov" in text
    assert_valid_html(text)


def test_1_recap_now_is_admin_only(db, monkeypatch):
    async def scenario():
        async with Harness() as h:
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", None)
            assert await h.text("/recap_now") == []
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)
            assert await h.text("/recap_now") == []          # UID 42 is not the admin
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
            out = await h.text("/recap_now")
            assert [p["chat_id"] for _, p in out] == [UID]
            assert "Recap preview" in out.texts[0]

    run(scenario())


# 2. Default account ----------------------------------------------------------
def test_2_without_default_the_account_is_asked(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("5")
            out = await h.tap("addcat_food")
            assert out.texts[-1] == "Which account?"

    run(scenario())


def test_2_with_default_the_account_step_is_skipped_and_can_be_changed(db):
    async def scenario():
        async with Harness() as h:
            await h.tap("setdefacc_mobile_money")
            await h.text(BTN_ADD)
            await h.text("5")
            out = await h.tap("addcat_food")
            assert "Which account?" not in out.texts
            assert "note" in out.texts[-1]
            out = await h.tap("skip_note")
            confirmation = out.texts[-2]
            assert "Mobile Wallets" in confirmation
            change = [b for b in out.buttons(-2) if b["text"] == "🔁 Change account"]
            assert change and out.has_main_keyboard(-1)

            entry_id = int(change[0]["callback_data"].split(":")[1])
            out = await h.tap(change[0]["callback_data"])
            assert any(b["callback_data"] == f"setacc:{entry_id}:bank" for b in out.buttons())
            out = await h.tap(f"setacc:{entry_id}:bank")
            assert "Bank" in out.texts[-1]
            assert transactions.get_entry(UID, entry_id)["account"] == "bank"
            assert accounts.account_balances(UID) == {"bank": -5.0}

    run(scenario())


def test_2_unset_default_reads_as_none(db):
    assert accounts.get_default_account(UID) is None


# 3. README -------------------------------------------------------------------
def test_3_every_command_in_readme_exists():
    from telegram.ext import CommandHandler

    from app.main import build_application

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    # Exact `/command` spans; commands sent to @BotFather and HTTP paths are not this bot's.
    mentioned = set(re.findall(r"`/(\w+)`", readme)) - {"newbot", "revoke", "setcommands", "healthz"}
    app = build_application()
    registered = set()
    for group in app.handlers.values():
        for handler in group:
            inner = [handler] + list(getattr(handler, "fallbacks", []))
            for x in inner:
                if isinstance(x, CommandHandler):
                    registered |= set(x.commands)
    assert mentioned, "README mentions no commands at all"
    assert mentioned <= registered, f"README mentions missing commands: {mentioned - registered}"


# 4. Summary periods and savings rate ------------------------------------------
def test_4_summary_uses_this_week_and_savings_rate(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD_INCOME)
            await h.text("1000")
            await h.tap("inccat_salary")
            await h.tap("incacc_cash")
            await h.tap("skip_income_note")
            await add_expense(h, amount="250")
            out = await h.tap("sum_week")
            text = out.texts[-1]
            assert "This week" in text and "Savings rate: 75%" in text and "Savings:" not in text
            await h.text(BTN_SUMMARY)

    run(scenario())


def test_4_savings_rate_hidden_without_income(db):
    async def scenario():
        async with Harness() as h:
            await add_expense(h, amount="40")
            out = await h.tap("sum_month")
            assert "This month" in out.texts[-1] and "Savings rate" not in out.texts[-1]

    run(scenario())


# 5. History labels -----------------------------------------------------------
def test_5_history_labels_and_signs(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_HISTORY)
            assert out.texts == [f"No transactions yet. Tap {BTN_ADD} or {BTN_ADD_INCOME} to log your first one."]
            await add_expense(h, amount="12.50")
            await h.text(BTN_ADD_INCOME)
            await h.text("300")
            await h.tap("inccat_gift")
            await h.tap("incacc_cash")
            await h.tap("skip_income_note")
            out = await h.text(BTN_HISTORY)
            assert out.texts[0] == "📋 <b>Recent transactions:</b>"
            assert "+300.00" in out.texts[1] and "Gift" in out.texts[1]
            assert f"{MINUS}12.50" in out.texts[2] and "Food" in out.texts[2]

    run(scenario())


# 6. HTML everywhere -----------------------------------------------------------
def test_6_gate_with_underscore_link_and_note_with_markup_characters(db, monkeypatch):
    monkeypatch.setattr(config, "CHANNEL_INVITE_LINK", "https://t.me/my_chan_name")

    async def scenario():
        async with Harness() as h:
            out = await add_expense(h, note="<b>lunch</b> * _x_ & co")
            assert all(p.get("parse_mode") == "HTML" for _, p in out)
            assert "&lt;b&gt;lunch&lt;/b&gt; * _x_ &amp; co" in out.texts[-1]
            out = await h.text(BTN_HISTORY)
            assert "&lt;b&gt;lunch" in out.texts[1]

            h.request.member_status = "left"
            membership_cache.clear()  # a member is trusted for 15 min; simulate that passing
            out = await h.text("/start")
            assert out[0][1]["parse_mode"] == "HTML" and "my_chan_name" in out.texts[0]

    run(scenario())


# 7. Flows never trap the user ---------------------------------------------------
def test_7_history_mid_entry_shows_history(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            out = await h.text(BTN_HISTORY)
            assert out.texts[0].startswith("No transactions yet") and out.has_main_keyboard(0)
            assert await h.text("50") == []   # the entry is gone; 50 is not an amount any more

    run(scenario())


def test_7_add_income_mid_expense_starts_income(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("5")
            out = await h.text(BTN_ADD_INCOME)
            assert "How much did you receive?" in out.texts[-1]
            out = await h.text("70")
            assert any(b.get("callback_data", "").startswith("inccat_") for b in out.buttons())

    run(scenario())


def test_7_cancel_on_every_step(db):
    async def scenario():
        async with Harness() as h:
            out = await h.text(BTN_ADD)                       # amount step: reply-keyboard Cancel
            assert [b["text"] for b in out.buttons()] == [BTN_CANCEL]
            out = await h.text("5")                           # category step: inline Cancel
            assert any(b.get("callback_data") == "flow_cancel" for b in out.buttons())
            out = await h.tap("addcat_food")                  # account step
            assert any(b.get("callback_data") == "flow_cancel" for b in out.buttons())
            out = await h.tap("addacc_cash")                  # note step
            assert any(b.get("callback_data") == "flow_cancel" for b in out.buttons())
            out = await h.tap("flow_cancel")
            assert "Nothing was saved" in out.texts[-1] and out.has_main_keyboard()
            assert transactions.list_recent(UID) == []

            await h.text(BTN_ADD)
            out = await h.text(BTN_CANCEL)
            assert out.has_main_keyboard()

            await h.tap("set_budget_start")
            await h.tap("budgetcat_food")
            out = await h.text(BTN_ACCOUNTS)
            assert out.has_main_keyboard(0) and "Account balances" in out.texts[-1]

    run(scenario())


def test_7_unfinished_entry_times_out(db):
    async def scenario():
        async with Harness(flow_timeout=1) as h:
            await h.text(BTN_ADD)
            h.request.sent.clear()
            await asyncio.sleep(2.5)
            assert any("timed out" in t for t in [p.get("text", "") for _, p in h.request.sent])
            assert await h.text("75") == []

    run(scenario())


def test_7_flow_timeout_is_ten_minutes():
    from app.bot.conversations import FLOW_TIMEOUT
    assert FLOW_TIMEOUT == 600


# 8. Database location ---------------------------------------------------------
def test_8_db_folder_created(fresh_db):
    assert not fresh_db.parent.exists()
    init_db()
    assert fresh_db.exists()


def test_8_default_path_follows_the_volume(monkeypatch, tmp_path):
    import importlib

    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    try:
        importlib.reload(config)
        assert config.DB_PATH == os.path.join(str(tmp_path), "expenses.db")
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_8_loud_warning_on_railway_without_volume(fresh_db, monkeypatch, caplog):
    from app.main import check_storage

    monkeypatch.setattr(config, "ON_RAILWAY", True)
    monkeypatch.setattr(config, "RAILWAY_VOLUME_MOUNT_PATH", "")
    with caplog.at_level(logging.INFO):
        check_storage()
    assert "WIPE" in caplog.text and str(fresh_db) in caplog.text

    caplog.clear()
    monkeypatch.setattr(config, "RAILWAY_VOLUME_MOUNT_PATH", str(fresh_db.parent))
    with caplog.at_level(logging.INFO):
        check_storage()
    assert "WIPE" not in caplog.text


# 9. .gitignore -----------------------------------------------------------------
@pytest.mark.parametrize("path", [".env", "finance_bot.db", "data/expenses.db", "expenses.db-wal",
                                  "backups/pre-migration-1.db", "app/__pycache__/x.pyc", ".pytest_cache/x"])
def test_9_gitignore_covers(path):
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO)
    assert result.returncode == 0, f"{path} is not ignored"
