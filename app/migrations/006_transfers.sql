-- Phase 4.5: transfers between a user's accounts. A transfer is an entry with
-- type 'transfer': `account` is where the money left, `to_account` where it
-- arrived. It changes both balances and never counts as income or expense.
ALTER TABLE expenses ADD COLUMN to_account TEXT;
