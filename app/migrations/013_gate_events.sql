-- Counting the members the gate brings in, and remembering where each user stands
-- in their current period (so leaving the current channel can be told apart from
-- never having joined). Only the user's required channel at the time is recorded.
CREATE TABLE IF NOT EXISTS gate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    period_number INTEGER NOT NULL,
    event TEXT NOT NULL,   -- shown, joined_via_bot, already_member, left, rejoined
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gate_events_channel ON gate_events (channel_id, event, at);
CREATE INDEX IF NOT EXISTS idx_gate_events_user ON gate_events (user_id, period_number);

-- One row per user and period: was the user a member the first time they were
-- checked, and are they a member now (as last seen)?
CREATE TABLE IF NOT EXISTS gate_user_periods (
    user_id INTEGER NOT NULL,
    period_number INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    member_at_first INTEGER NOT NULL,
    member_now INTEGER NOT NULL,
    PRIMARY KEY (user_id, period_number)
);

-- The invite link is now one permanent "Finance Bot" link per channel, kept until it
-- is revoked: forget the short-lived ones made before.
UPDATE gate_channels SET invite_link = NULL, invite_link_at = NULL;
