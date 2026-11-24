-- The schema the bot had before migrations existed (database.py init_db + _migrate).
-- On an existing database every statement is a no-op, so the file is recognised,
-- not recreated. Older tables missing type/account are brought up to date by the
-- runner (app/db.py) right after this file.

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'expense',
    account TEXT NOT NULL DEFAULT 'cash'
);

CREATE TABLE IF NOT EXISTS budgets (
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (user_id, category)
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    default_account TEXT NOT NULL DEFAULT 'cash'
);
