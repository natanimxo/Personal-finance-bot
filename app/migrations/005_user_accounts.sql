-- Phase 4.4: accounts that fit the user. Each user has their own list; entries
-- keep pointing at the account's key, so a rename keeps history and balance.
CREATE TABLE IF NOT EXISTS accounts (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key)
);

-- Existing users keep exactly the four accounts they had.
WITH known(user_id) AS (
    SELECT user_id FROM users UNION SELECT user_id FROM expenses
    UNION SELECT user_id FROM user_settings UNION SELECT user_id FROM budgets
)
INSERT OR IGNORE INTO accounts (user_id, key, name, position)
SELECT user_id, 'cash', '💵 Cash', 0 FROM known UNION ALL
SELECT user_id, 'bank', '🏦 Bank', 1 FROM known UNION ALL
SELECT user_id, 'card', '💳 Card', 2 FROM known UNION ALL
SELECT user_id, 'mobile_money', '📱 Mobile Wallets', 3 FROM known;
