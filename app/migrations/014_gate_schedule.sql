-- One global schedule for the channel gate, shared by every user: no free period.
-- Period n = floor((now - start_at) / 30 days); its channel is the one n places
-- after start_channel in the list order, round again.
-- 2026-11-24 00:00 Africa/Nairobi (UTC+3) = 2026-11-23 21:00 UTC; We Talk A Lot.
INSERT OR IGNORE INTO gate_settings (key, value) VALUES ('start_at', '2026-11-23T21:00:00');
INSERT OR IGNORE INTO gate_settings (key, value) VALUES ('start_channel', '-1004376927203');
