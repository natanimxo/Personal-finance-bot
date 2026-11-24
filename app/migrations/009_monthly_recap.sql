-- Phase 4.11: a monthly recap on the 1st, with its own off switch and its own
-- "already sent" marker (so a restart mid-run sends no duplicates).
ALTER TABLE user_prefs ADD COLUMN monthly_recap_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN last_monthly_recap_sent TEXT;
