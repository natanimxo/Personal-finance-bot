"""Daily database backups.

At 03:00 (APP_TIMEZONE) a copy is written with SQLite's backup API to
backups/expenses-YYYY-MM-DD.db next to the database. The newest 7 daily copies
are kept, plus the newest copy of each of the 4 weeks before them. A gzipped
copy also goes to ADMIN_CHAT_ID, so a backup exists off the server too.
"""
import gzip
import io
import logging
import os
import re
import sqlite3
from datetime import date, timedelta

from app import config
from app.services import periods

logger = logging.getLogger(__name__)

NAME = re.compile(r"^expenses-(\d{4}-\d{2}-\d{2})\.db$")
KEEP_DAILY = 7
KEEP_WEEKLY = 4


def backup_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)), "backups")


def make_backup(today: date = None) -> str:
    """Write today's backup (replacing an earlier one from the same day). Returns its path."""
    today = today or periods.now_local().date()
    folder = backup_dir()
    os.makedirs(folder, exist_ok=True)
    final = os.path.join(folder, f"expenses-{today.isoformat()}.db")
    partial = final + ".partial"
    src = sqlite3.connect(config.DB_PATH)
    dest = sqlite3.connect(partial)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    os.replace(partial, final)
    return final


def files_to_keep(names, today: date):
    """Which of the backup file names survive pruning."""
    dated = sorted(
        ((date.fromisoformat(m.group(1)), n) for n in names if (m := NAME.match(n))), reverse=True
    )
    keep = set()
    daily_cutoff = today - timedelta(days=KEEP_DAILY - 1)
    for day, name in dated:
        if day >= daily_cutoff:
            keep.add(name)
    weeks_seen = []
    for day, name in dated:
        if day >= daily_cutoff:
            continue
        week = day.isocalendar()[:2]
        if week in weeks_seen:
            continue  # an older copy from a week we already keep
        if len(weeks_seen) == KEEP_WEEKLY:
            break
        weeks_seen.append(week)
        keep.add(name)
    return keep


def prune(today: date = None) -> list:
    """Delete backups outside the 7 daily + 4 weekly window. Returns the deleted names."""
    today = today or periods.now_local().date()
    folder = backup_dir()
    if not os.path.isdir(folder):
        return []
    names = [n for n in os.listdir(folder) if NAME.match(n)]
    keep = files_to_keep(names, today)
    removed = []
    for name in names:
        if name not in keep:
            os.remove(os.path.join(folder, name))
            removed.append(name)
    return removed


def gzipped(path: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with open(path, "rb") as f, gzip.GzipFile(fileobj=buffer, mode="wb", filename=os.path.basename(path)) as gz:
        gz.write(f.read())
    buffer.seek(0)
    return buffer


async def send_to_admin(bot, path: str):
    if config.ADMIN_CHAT_ID is None:
        return False
    data = gzipped(path)
    name = os.path.basename(path) + ".gz"
    size_kb = os.path.getsize(path) / 1024
    await bot.send_document(
        chat_id=config.ADMIN_CHAT_ID,
        document=data,
        filename=name,
        caption=f"🗄️ Database backup {name} ({size_kb:.0f} KB before compression)",
    )
    return True


async def run_backup(bot, today: date = None) -> str:
    """Make, prune and send one backup. Used by the 03:00 job and /backup_now."""
    from app.db import db_call

    path = await db_call(make_backup, today)
    removed = await db_call(prune, today)
    logger.info("Backup written to %s; pruned %d old copies", path, len(removed))
    try:
        await send_to_admin(bot, path)
    except Exception as e:
        logger.error(f"Backup made but sending it to the admin failed: {e}")
    return path


async def daily_backup_job(context):
    await run_backup(context.bot)


def restore(backup_path: str, target_path: str):
    """Copy a backup (.db or .db.gz) into place. Run only while the bot is stopped."""
    opener = gzip.open if backup_path.endswith(".gz") else open
    with opener(backup_path, "rb") as f:
        data = f.read()
    folder = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(folder, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(target_path + suffix):
            os.remove(target_path + suffix)
    with open(target_path, "wb") as f:
        f.write(data)
    # Sanity check: the restored file opens and has the expected tables.
    conn = sqlite3.connect(target_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    if "expenses" not in tables:
        raise ValueError(f"{backup_path} does not look like an expense bot database")
    return target_path


def _check_database(path: str):
    """Raises ValueError unless `path` is a readable expense-bot database."""
    try:
        conn = sqlite3.connect(path)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("the file is damaged (integrity check failed)")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(f"not an SQLite database ({e})")
    if "expenses" not in tables:
        raise ValueError("this SQLite file has no expenses table")


def restore_live(data: bytes) -> dict:
    """Put a rescued or backed-up database (.db or .db.gz bytes) in place while the
    bot is running, e.g. right after attaching a Railway volume.

    The file is checked first; the current database is backed up to backups/;
    then SQLite's backup API copies the file into the live database (safe with
    other connections open); then the migrations bring an older file up to date.
    Returns row counts after the restore."""
    import tempfile

    from app.db import backup_database, get_conn, run_migrations

    if data[:2] == b"\x1f\x8b":  # gzip magic number
        data = gzip.decompress(data)
    with tempfile.TemporaryDirectory() as tmp:
        incoming = os.path.join(tmp, "incoming.db")
        with open(incoming, "wb") as f:
            f.write(data)
        _check_database(incoming)
        safety = backup_database("pre-restore") if os.path.exists(config.DB_PATH) else None
        src = sqlite3.connect(incoming)
        dest = sqlite3.connect(config.DB_PATH)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
    applied = run_migrations()
    with get_conn() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("expenses", "users", "budgets")}
    logger.warning("Database restored from an uploaded file (%s); migrations applied: %s; safety copy: %s",
                   counts, applied, safety)
    return {"counts": counts, "migrations": applied, "safety_copy": safety}


if __name__ == "__main__":
    # python -m app.services.backup restore <backup file> [target path]
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "restore":
        target = sys.argv[3] if len(sys.argv) > 3 else config.DB_PATH
        restore(sys.argv[2], target)
        print(f"Restored {sys.argv[2]} to {target}")
    else:
        print("usage: python -m app.services.backup restore <backup.db|backup.db.gz> [target]")
        sys.exit(2)
