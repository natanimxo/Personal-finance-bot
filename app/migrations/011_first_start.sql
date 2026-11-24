-- The channel gate: each user's first 30 days are free, counted from their first
-- contact with the bot. Users who already exist start counting from their next
-- message (set by users.register_user), so nobody is asked to join straight away.
ALTER TABLE users ADD COLUMN first_start_at TEXT;
