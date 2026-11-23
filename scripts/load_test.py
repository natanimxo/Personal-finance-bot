"""Phase 2 acceptance: python scripts/load_test.py [users]

1. 1,000 users each log 5 entries from 50 threads at once (with the budget check
   and a history read after every entry): no "database is locked" errors.
2. The weekly recap goes to 1,000 users through a fake Telegram that answers
   429 above 30 messages a second: no 429s.
3. A backup is made, gzipped as it would arrive in the admin chat, restored into
   a fresh folder, and the restored database starts and matches.

Runs against a temporary database; nothing real is touched. Takes ~2 minutes.
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
work = Path(tempfile.mkdtemp(prefix="expense-load-"))
os.environ.update(BOT_TOKEN="1:load-test", CHANNEL_ID="@load_test", CHANNEL_LINK="https://t.me/load_test",
                  DB_PATH=str(work / "data" / "expenses.db"))

from app import config  # noqa: E402
from app.db import get_conn, init_db  # noqa: E402
from app.services import backup, budgets, periods, recap, transactions, users  # noqa: E402
from tests.fake_telegram import Harness  # noqa: E402

USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
ENTRIES = 5
WEDNESDAY = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
failures = []


def one_user(user_id):
    errors = []
    for i in range(ENTRIES):
        try:
            users.register_user(user_id)
            entry = transactions.add_expense(user_id, 10 + i, "food", f"entry {i}")
            with get_conn() as conn:  # date it last week so the recap has something to send
                conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", ("2026-11-18T09:00:00", entry))
            budgets.month_total_for_category(user_id, "food", periods.month_start())
            transactions.list_recent(user_id)
        except sqlite3.OperationalError as e:
            errors.append(str(e))
    return errors


def part1():
    init_db()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=50) as pool:
        errors = [e for errs in pool.map(one_user, range(1, USERS + 1)) for e in errs]
    elapsed = time.monotonic() - started
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    locked = [e for e in errors if "locked" in e]
    print(f"1. {USERS} users x {ENTRIES} entries from 50 threads: {count} rows in {elapsed:.1f}s, "
          f"{len(errors)} database errors ({len(locked)} 'database is locked')")
    if errors or count != USERS * ENTRIES:
        failures.append("part 1")


async def part2():
    async with Harness(rate_limit=30) as h:
        started = time.monotonic()
        stats = await recap.run_recap(SimpleNamespace(bot=h.app.bot), now=WEDNESDAY)
        elapsed = time.monotonic() - started
        print(f"2. Recap to {USERS} users: {stats} in {elapsed:.1f}s "
              f"({stats['sent'] / elapsed:.1f} msg/s), 429 responses: {h.request.too_many}")
        if h.request.too_many or stats["sent"] != USERS:
            failures.append("part 2")


def part3():
    path = backup.make_backup()
    gz = work / "from-admin-chat.db.gz"
    gz.write_bytes(backup.gzipped(path).read())
    fresh = work / "fresh-environment" / "expenses.db"
    backup.restore(str(gz), str(fresh))
    original = config.DB_PATH
    config.DB_PATH = str(fresh)
    init_db()
    with get_conn() as conn:
        restored = conn.execute("SELECT COUNT(*), SUM(amount) FROM expenses").fetchone()[:]
        sent = conn.execute("SELECT COUNT(*) FROM users WHERE last_recap_sent IS NOT NULL").fetchone()[0]
    config.DB_PATH = original
    with get_conn() as conn:
        live = conn.execute("SELECT COUNT(*), SUM(amount) FROM expenses").fetchone()[:]
    print(f"3. Backup {Path(path).name} ({os.path.getsize(path) / 1024:.0f} KB, "
          f"{gz.stat().st_size / 1024:.0f} KB gzipped) restored into a fresh folder: "
          f"{restored[0]} rows, total {restored[1]:.0f} (live: {live[0]} rows, total {live[1]:.0f}); "
          f"{sent} users' recap state kept")
    if restored != live:
        failures.append("part 3")


part1()
asyncio.run(part2())
part3()
print("PASS" if not failures else f"FAIL: {', '.join(failures)}")
sys.exit(1 if failures else 0)
