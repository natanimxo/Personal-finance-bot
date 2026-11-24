-- Phase 3: exact money and per-user settings.

-- Amounts were REAL (floats). amount_minor holds the same value as an integer
-- number of cents (amount x 100), so totals are exact. Every read now uses
-- amount_minor. The old amount column is kept, and still written, until the
-- startup check (app/db.py) has confirmed both totals match on live data.
ALTER TABLE expenses ADD COLUMN amount_minor INTEGER;
UPDATE expenses SET amount_minor = CAST(ROUND(amount * 100) AS INTEGER);

ALTER TABLE budgets ADD COLUMN amount_minor INTEGER;
UPDATE budgets SET amount_minor = CAST(ROUND(amount * 100) AS INTEGER);

-- Settings the Mini App changes. A separate table, because a row in
-- user_settings means "this user picked a default account".
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY,
    currency TEXT,
    recap_enabled INTEGER NOT NULL DEFAULT 1
);
