-- The channel gate lives in the database, managed with admin commands
-- (/gate_add, /gate_remove, /gate_list, /gate_on, /gate_off), not env vars.
-- Channels are stored by numeric chat id only, so renaming a channel (or the bot)
-- breaks nothing. Titles and invite links are fetched from Telegram and only
-- cached here (24 hours).
CREATE TABLE IF NOT EXISTS gate_channels (
    chat_id INTEGER PRIMARY KEY,
    position INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    title TEXT,
    title_at TEXT,
    invite_link TEXT,
    invite_link_at TEXT
);

CREATE TABLE IF NOT EXISTS gate_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Off until an admin sends /gate_on.
INSERT OR IGNORE INTO gate_settings (key, value) VALUES ('enabled', '0');

-- The rotation the owner gave, in order (users rotate through these every 30 days).
INSERT OR IGNORE INTO gate_channels (chat_id, position, added_at) VALUES
    (-1002704031424, 1, '2026-11-24T00:00:00'),
    (-1002905948541, 2, '2026-11-24T00:00:00'),
    (-1004376927203, 3, '2026-11-24T00:00:00'),
    (-1001992993907, 4, '2026-11-24T00:00:00'),
    (-1001897854375, 5, '2026-11-24T00:00:00'),
    (-1001200205264, 6, '2026-11-24T00:00:00');
