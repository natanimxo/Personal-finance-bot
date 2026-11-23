-- Phase 4.10: custom categories per user, for expenses and income. Entries keep
-- pointing at the category key, so a rename keeps history, and a hidden category
-- still counts in summaries. Users start from the built-in list (filled in the
-- first time their categories are read).
CREATE TABLE IF NOT EXISTS categories (
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,              -- 'expense' or 'income'
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, type, key)
);
