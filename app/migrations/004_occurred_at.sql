-- Phase 4.3: past dates. occurred_at is when the money moved; created_at stays
-- when it was logged. Existing rows happened when they were logged.
ALTER TABLE expenses ADD COLUMN occurred_at TEXT;
UPDATE expenses SET occurred_at = created_at;
CREATE INDEX IF NOT EXISTS idx_expenses_user_occurred ON expenses (user_id, occurred_at);
