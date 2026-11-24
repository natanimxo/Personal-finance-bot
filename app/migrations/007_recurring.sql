-- Phase 4.7: recurring entries (rent, salary, subscriptions).
-- next_date is the local date of the next entry to create. The job advances it
-- in the same transaction that inserts the entry, so a restart can't duplicate.
CREATE TABLE IF NOT EXISTS recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    category TEXT NOT NULL,
    account TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL,          -- 'weekly' or 'monthly'
    anchor_day INTEGER NOT NULL,      -- monthly: day of month 1-31 (clamped to short months)
    next_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recurring_due ON recurring (next_date);
CREATE INDEX IF NOT EXISTS idx_recurring_user ON recurring (user_id);
