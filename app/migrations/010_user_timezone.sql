-- Worldwide: each user picks their own currency and timezone when they start.
-- NULL means "not chosen yet": the bot asks on /start. Weeks, months, budgets,
-- recaps and recurring entries then follow the user's own clock.
ALTER TABLE user_prefs ADD COLUMN timezone TEXT;
