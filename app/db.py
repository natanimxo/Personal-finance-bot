"""SQLite connection and the numbered-migrations runner.

Migrations live in app/migrations as NNN_name.sql and are applied in order,
each once, recorded in schema_version. They are additive only: nothing here
drops or rewrites existing data. Before the first pending migration runs on a
database that already holds tables, a copy is written to backups/ next to it.
"""
import asyncio
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app import config

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def db_path() -> str:
    return config.DB_PATH


# Applied on every connection. WAL lets readers work while one writer writes;
# busy_timeout makes a writer wait up to 5 s for a lock instead of failing.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
)


@contextmanager
def get_conn():
    conn = sqlite3.connect(db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


async def db_call(fn, *args, **kwargs):
    """Run a blocking database function in a worker thread, off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def ping() -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT 1").fetchone()[0] == 1


def _migration_files():
    files = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        m = re.match(r"^(\d{3})_.+\.sql$", name)
        if m:
            files.append((int(m.group(1)), name))
    return files


def _existing_tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def backup_database(label: str) -> str:
    """Copy the live database with SQLite's backup API. Returns the backup path."""
    src_path = db_path()
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(src_path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = os.path.join(backup_dir, f"{label}-{stamp}.db")
    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    return dest_path


def _ensure_legacy_columns(conn):
    """Databases from before type/account existed: add them (same as the old _migrate)."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(expenses)").fetchall()]
    if "type" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'")
    if "account" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN account TEXT NOT NULL DEFAULT 'cash'")


def run_migrations():
    with get_conn() as conn:
        tables = _existing_tables(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {r["version"] for r in conn.execute("SELECT version FROM schema_version")}
    pending = [(v, n) for v, n in _migration_files() if v not in applied]
    if not pending:
        return []

    had_data = bool(tables - {"schema_version"})
    if had_data:
        path = backup_database("pre-migration")
        logger.info("Backed up the database to %s before running %d migration(s)", path, len(pending))

    done = []
    for version, name in pending:
        sql = open(os.path.join(MIGRATIONS_DIR, name), encoding="utf-8").read()
        with get_conn() as conn:
            conn.executescript(sql)
            if version == 1:
                # 001 describes the schema the bot already had. On an existing
                # database its CREATE TABLE IF NOT EXISTS statements are no-ops,
                # so bring any older table up to that shape here.
                _ensure_legacy_columns(conn)
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(timezone.utc).isoformat()),
            )
        done.append(name)
        logger.info("Applied migration %s", name)
    return done


def check_amount_columns() -> bool:
    """The float `amount` column is kept until it provably matches amount_minor.
    Logs the result; returns True when every row and the totals agree."""
    with get_conn() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(expenses)")]
        if "amount_minor" not in cols:
            return True
        mismatched = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE amount_minor IS NULL "
            "OR amount_minor <> CAST(ROUND(amount * 100) AS INTEGER)"
        ).fetchone()[0]
        old_total, new_total = conn.execute(
            "SELECT ROUND(COALESCE(SUM(amount), 0), 2), COALESCE(SUM(amount_minor), 0) FROM expenses"
        ).fetchone()
    ok = mismatched == 0 and round(old_total * 100) == new_total
    log = logger.info if ok else logger.error
    log("amount vs amount_minor: %d mismatched rows; totals %.2f vs %.2f", mismatched, old_total, new_total / 100)
    return ok


def init_db():
    folder = os.path.dirname(db_path())
    if folder:
        os.makedirs(folder, exist_ok=True)
    run_migrations()
    check_amount_columns()
