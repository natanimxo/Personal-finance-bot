"""Phase 2: ready for about 1,000 users."""
import asyncio
import gzip
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config
from app.bot import membership
from app.bot.errors import on_error, throttle
from app.bot.keyboards import BTN_ADD, BTN_HISTORY, parse_amount
from app.db import get_conn, init_db
from app.services import backup, periods, recap, transactions, users
from tests.fake_telegram import UID, Harness, run

REPO = Path(__file__).resolve().parent.parent
WEDNESDAY = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
LAST_WEEK = "2026-11-18T09:00:00"  # Wed 18 Nov, inside the week before WEDNESDAY


@pytest.fixture
def db(fresh_db):
    init_db()
    return fresh_db


def add_last_week_entry(user_id, amount=10):
    users.register_user(user_id)
    entry = transactions.add_expense(user_id, amount, "food")
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", (LAST_WEEK, entry))


# --- SQLite tuning ----------------------------------------------------------------
def test_every_connection_is_tuned(db):
    with get_conn() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_indexes_exist(db):
    with get_conn() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_expenses_user_created", "idx_expenses_user_category"} <= names


def test_handlers_never_call_the_database_on_the_event_loop():
    source = (REPO / "app" / "bot" / "handlers.py").read_text(encoding="utf-8")
    source += (REPO / "app" / "bot" / "membership.py").read_text(encoding="utf-8")
    direct = re.findall(r"(?<!db_call\()\b(accounts|budgets|summaries|transactions|users)\.\w+\(", source)
    assert direct == [], f"blocking database calls in async handlers: {direct}"


# --- Membership cache --------------------------------------------------------------
def test_membership_positive_result_is_cached(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_HISTORY)
            await h.text(BTN_HISTORY)
            await h.text(BTN_HISTORY)
            assert h.request.member_checks == 1

    run(scenario())


def test_membership_negative_result_is_not_cached(db):
    async def scenario():
        async with Harness() as h:
            h.request.member_status = "left"
            await h.text(BTN_HISTORY)
            await h.text(BTN_HISTORY)
            assert h.request.member_checks == 2
            h.request.member_status = "member"      # they join...
            out = await h.text(BTN_HISTORY)         # ...and are let in at once
            assert "No transactions yet" in out.texts[0]

    run(scenario())


def test_ive_subscribed_always_checks_live(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_HISTORY)
            await h.tap("recheck_sub")
            await h.tap("recheck_sub")
            assert h.request.member_checks == 3

    run(scenario())


def test_cache_expires_after_15_minutes():
    clock = [0.0]
    cache = membership.MembershipCache(clock=lambda: clock[0])
    cache.store(1, True)
    clock[0] = 14 * 60
    assert cache.fresh(1)
    clock[0] = 15 * 60
    assert not cache.fresh(1)


def test_telegram_error_uses_last_known_result(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_HISTORY)                 # known member
            membership.membership_cache._subscribed_at.clear()  # cache expired
            h.request.member_error = True
            out = await h.text(BTN_HISTORY)
            assert "No transactions yet" in out.texts[0]   # not locked out

            membership.membership_cache.clear()        # nothing known about them
            out = await h.text(BTN_HISTORY)
            assert "join my channel" in out.texts[0]

    run(scenario())


# --- Weekly recap ------------------------------------------------------------------
def recap_context(h):
    return SimpleNamespace(bot=h.app.bot)


def test_recap_is_not_sent_twice_in_one_week(db):
    for uid in (1, 2, 3):
        add_last_week_entry(uid)

    async def scenario():
        async with Harness() as h:
            first = await recap.run_recap(recap_context(h), now=WEDNESDAY, rate=1000)
            again = await recap.run_recap(recap_context(h), now=WEDNESDAY, rate=1000)
            assert first["sent"] == 3 and again["sent"] == 0
            assert sorted(h.request.delivered) == [1, 2, 3]

    run(scenario())


def test_restart_mid_recap_continues_without_duplicates(db):
    for uid in range(1, 7):
        add_last_week_entry(uid)
    week_key = periods.previous_week(WEDNESDAY)[0].date().isoformat()
    for uid in (1, 2, 3):              # the run that crashed had reached user 3
        users.mark_recap_sent(uid, week_key)

    async def scenario():
        async with Harness() as h:
            stats = await recap.run_recap(recap_context(h), now=WEDNESDAY, rate=1000)
            assert stats["sent"] == 3 and sorted(h.request.delivered) == [4, 5, 6]

    run(scenario())


def test_blocked_user_is_marked_inactive_and_comes_back(db):
    add_last_week_entry(UID)
    add_last_week_entry(7)

    async def scenario():
        async with Harness() as h:
            h.request.forbidden_chats = {UID}
            stats = await recap.run_recap(recap_context(h), now=WEDNESDAY, rate=1000)
            assert stats["blocked"] == 1 and stats["sent"] == 1
            assert not users.is_active(UID)

            next_week = WEDNESDAY + timedelta(days=7)
            stats = await recap.run_recap(recap_context(h), now=next_week, rate=1000)
            assert stats["blocked"] == 0  # skipped, not even tried

            h.request.forbidden_chats = set()
            await h.text(BTN_HISTORY)      # they unblock the bot and write to it
            assert users.is_active(UID)

    run(scenario())


def test_recap_stays_under_the_rate_limit(db):
    for uid in range(1, 61):
        add_last_week_entry(uid)

    async def scenario():
        async with Harness(rate_limit=30) as h:
            started = time.monotonic()
            stats = await recap.run_recap(recap_context(h), now=WEDNESDAY, rate=25)
            elapsed = time.monotonic() - started
            assert stats["sent"] == 60
            assert h.request.too_many == 0
            assert elapsed >= 59 / 25 * 0.95   # paced, not a burst

    run(scenario())


# --- Backups -----------------------------------------------------------------------
def test_backup_file_name_and_contents(db):
    transactions.add_expense(UID, 5, "food")
    path = backup.make_backup(date(2026, 11, 23))
    assert Path(path).name == "expenses-2026-11-23.db"
    assert Path(path).parent == db.parent / "backups"
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    copy.close()


def test_retention_keeps_7_daily_and_4_weekly():
    today = date(2026, 11, 23)
    names = [f"expenses-{(today - timedelta(days=d)).isoformat()}.db" for d in range(60)]
    keep = backup.files_to_keep(names + ["pre-migration-1.db", "notes.txt"], today)
    days = sorted(date.fromisoformat(n[9:19]) for n in keep)
    assert len(keep) == 11
    assert days[-7:] == [today - timedelta(days=d) for d in range(6, -1, -1)]
    older = days[:-7]
    assert len({d.isocalendar()[:2] for d in older}) == 4  # one per week
    assert all(d < today - timedelta(days=6) for d in older)


def test_prune_only_touches_dated_backups(db):
    folder = Path(backup.backup_dir())
    folder.mkdir(parents=True, exist_ok=True)
    for d in range(30):
        (folder / f"expenses-{(date(2026, 11, 23) - timedelta(days=d)).isoformat()}.db").write_bytes(b"x")
    (folder / "pre-migration-20261101.db").write_bytes(b"x")
    removed = backup.prune(date(2026, 11, 23))
    assert len(removed) == 30 - 11
    assert (folder / "pre-migration-20261101.db").exists()


def test_backup_restores_into_a_fresh_environment(db, tmp_path, monkeypatch):
    for uid in range(1, 21):
        transactions.add_expense(uid, uid, "food", "note")
    path = backup.make_backup(date(2026, 11, 23))
    gz = tmp_path / "from-admin-chat.db.gz"
    gz.write_bytes(backup.gzipped(path).read())

    fresh = tmp_path / "new-server" / "expenses.db"
    backup.restore(str(gz), str(fresh))
    monkeypatch.setattr(config, "DB_PATH", str(fresh))
    init_db()  # the new environment starts up on the restored file
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*), SUM(amount) FROM expenses").fetchone()[:] == (20, 210)


def test_restore_refuses_a_file_that_is_not_a_database(tmp_path):
    bogus = tmp_path / "x.db"
    sqlite3.connect(bogus).close()
    with pytest.raises(ValueError):
        backup.restore(str(bogus), str(tmp_path / "out.db"))


def test_backup_now_is_admin_only_and_sends_a_gzip(db, monkeypatch):
    async def scenario():
        async with Harness() as h:
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)
            assert await h.text("/backup_now") == []
            monkeypatch.setattr(config, "ADMIN_CHAT_ID", UID)
            out = await h.text("/backup_now")
            documents = [p for e, p in out if e == "sendDocument"]
            assert documents and documents[0]["chat_id"] == UID
            assert list(Path(backup.backup_dir()).glob("expenses-*.db"))

    run(scenario())


def test_gzip_copy_round_trips(db):
    path = backup.make_backup(date(2026, 11, 23))
    assert gzip.decompress(backup.gzipped(path).read()) == Path(path).read_bytes()


def test_backup_and_recap_jobs_are_scheduled(db):
    from zoneinfo import ZoneInfo

    h = Harness()

    async def jobs():
        async with h:
            return {j.name: j.next_t.astimezone(ZoneInfo(config.APP_TIMEZONE)) for j in h.app.job_queue.jobs()}

    scheduled = run(jobs())
    assert scheduled["daily_backup"].strftime("%H:%M") == "03:00"
    assert scheduled["weekly_recap"].strftime("%A %H:%M") == "Monday 08:00"


# --- Errors and health -------------------------------------------------------------
def test_error_alert_goes_to_admin_at_most_once_a_minute(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", 999)

    async def scenario():
        async with Harness() as h:
            ctx = SimpleNamespace(bot=h.app.bot, error=RuntimeError("boom <x>"))
            h.request.sent.clear()
            await on_error(None, ctx)
            await on_error(None, ctx)
            await on_error(None, ctx)
            alerts = [p for e, p in h.request.sent if e == "sendMessage"]
            assert len(alerts) == 1 and "boom &lt;x&gt;" in alerts[0]["text"]

            throttle.last -= 61
            await on_error(None, ctx)
            alerts = [p for e, p in h.request.sent if e == "sendMessage"]
            assert len(alerts) == 2 and "2 more error(s)" in alerts[1]["text"]

    run(scenario())


# /healthz is served by the FastAPI app since Phase 3: see tests/test_api.py::test_healthz.


# --- Input validation --------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [("1500", 1500), ("1,500", 1500), ("1500.50", 1500.5),
                                           ("1 500", 1500), ("0.5", 0.5), ("12.500", 12.5)])
def test_amounts_accepted(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text,reason", [("12.345", "2 decimal"), ("0", "more than 0"), ("-5", "amount"),
                                         ("100000001", "maximum"), ("1e5", "amount"), ("abc", "amount"),
                                         ("", "amount"), ("nan", "amount")])
def test_amounts_rejected(text, reason):
    with pytest.raises(ValueError, match=reason):
        parse_amount(text)


def test_long_note_is_refused_and_the_entry_stays_open(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("5")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            out = await h.text("x" * 201)
            assert "up to 200 characters" in out.texts[0]
            assert transactions.list_recent(UID) == []
            out = await h.text("y" * 200)
            assert "Logged" in out.texts[-1]
            assert len(transactions.list_recent(UID)[0]["note"]) == 200

    run(scenario())


def test_bad_amount_message_says_why(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            out = await h.text("12.345")
            assert "2 decimal places" in out.texts[0]

    run(scenario())


def test_membership_checks_are_not_throttled_like_group_messages(db):
    """getChatMember names the channel; it must not wait behind the 20/min group limit."""
    async def scenario():
        async with Harness() as h:
            started = time.monotonic()
            for uid in range(1, 41):
                await membership.is_subscribed(SimpleNamespace(bot=h.app.bot), uid, live=True)
            assert h.request.member_checks == 40
            assert time.monotonic() - started < 5

    run(scenario())
