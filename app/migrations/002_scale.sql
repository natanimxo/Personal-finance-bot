-- Phase 2: users who blocked the bot, restart-safe recaps, and indexes for 1,000+ users.

-- 0 after Telegram answers Forbidden (the user blocked the bot); back to 1 when they write again.
ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1;

-- Monday (YYYY-MM-DD) of the last week whose recap this user was sent, so a
-- restart in the middle of a recap run never sends anyone a second copy.
ALTER TABLE users ADD COLUMN last_recap_sent TEXT;

-- Entries are stored in the expenses table; created_at is the entry time until
-- Phase 4 adds occurred_at (which gets its own index then).
CREATE INDEX IF NOT EXISTS idx_expenses_user_created ON expenses (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_expenses_user_category ON expenses (user_id, category);
