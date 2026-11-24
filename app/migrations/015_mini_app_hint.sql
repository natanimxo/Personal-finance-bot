-- Gently suggest the Mini App to people who log entries by hand in the chat:
-- count the entries logged in the bot, and remember anyone who has opened the app
-- (they are never nudged).
ALTER TABLE users ADD COLUMN bot_entries INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN app_seen_at TEXT;
