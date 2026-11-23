import sqlite3

from app import db


OLD_SCHEMA = """
CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    amount REAL NOT NULL, category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE budgets (user_id INTEGER NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
    PRIMARY KEY (user_id, category));
CREATE TABLE users (user_id INTEGER PRIMARY KEY);
INSERT INTO users VALUES (7);
INSERT INTO expenses (user_id, amount, category, note, created_at)
    VALUES (7, 12.5, 'food', 'lunch', '2026-07-01T10:00:00');
INSERT INTO budgets VALUES (7, 'food', 200);
"""


def test_fresh_database_gets_schema(fresh_db):
    db.init_db()
    assert fresh_db.exists()
    with db.get_conn() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version")]
    assert {"expenses", "budgets", "users", "user_settings", "schema_version"} <= tables
    assert versions == [1]
    assert not (fresh_db.parent / "backups").exists()  # nothing to back up on an empty database


def test_existing_database_is_recognised_not_recreated(fresh_db):
    fresh_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(fresh_db)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    db.init_db()

    with db.get_conn() as conn:
        row = dict(conn.execute("SELECT * FROM expenses").fetchone())
        assert conn.execute("SELECT amount FROM budgets").fetchone()[0] == 200
    assert row["amount"] == 12.5 and row["note"] == "lunch"
    assert row["type"] == "expense" and row["account"] == "cash"
    backups = list((fresh_db.parent / "backups").glob("pre-migration-*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    assert copy.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    copy.close()


def test_migrations_run_once(fresh_db):
    db.init_db()
    assert db.run_migrations() == []


def test_app_builds(fresh_db):
    from app.main import build_application
    from app.services.recap import send_weekly_recap

    application = build_application()
    assert sum(len(h) for h in application.handlers.values()) > 10
    assert any(j.callback is send_weekly_recap for j in application.job_queue.jobs())
