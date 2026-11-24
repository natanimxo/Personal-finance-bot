"""Problem 4: one definition of week and month, in the user's timezone. These use
Africa/Nairobi (UTC+3); tests/test_worldwide.py covers other zones."""
from datetime import datetime, timezone

import pytest

from app.services import budgets, periods, summaries, transactions
from app.db import get_conn, init_db

UTC = timezone.utc


def utc(*args):
    return datetime(*args, tzinfo=UTC)


@pytest.fixture(autouse=True)
def nairobi():
    with periods.use_zone("Africa/Nairobi"):
        yield


def test_week_starts_monday_midnight_local():
    # Sunday 29 Nov 2026 20:59 UTC = Sunday 23:59 Nairobi: still the week of Mon 23 Nov.
    assert periods.week_start(utc(2026, 11, 29, 20, 59)).strftime("%a %Y-%m-%d %H:%M") == "Mon 2026-11-23 00:00"
    # Sunday 21:00 UTC = Monday 00:00 Nairobi: a new week.
    assert periods.week_start(utc(2026, 11, 29, 21, 0)).strftime("%a %Y-%m-%d %H:%M") == "Mon 2026-11-30 00:00"


def test_month_starts_on_the_first_local():
    # 30 Nov 21:30 UTC is already 1 Dec 00:30 in Nairobi.
    assert periods.month_start(utc(2026, 11, 30, 21, 30)).strftime("%Y-%m-%d %H:%M") == "2026-12-01 00:00"
    assert periods.month_start(utc(2026, 11, 30, 20, 30)).strftime("%Y-%m-%d %H:%M") == "2026-11-01 00:00"


def test_previous_week_is_monday_to_monday():
    start, end = periods.previous_week(utc(2026, 11, 25, 12, 0))  # a Wednesday
    assert start.strftime("%a %d %b %H:%M") == "Mon 16 Nov 00:00"
    assert end.strftime("%a %d %b %H:%M") == "Mon 23 Nov 00:00"


def test_to_db_matches_stored_format():
    # Monday 00:00 Nairobi is Sunday 21:00 UTC, stored as naive ISO text.
    assert periods.to_db(periods.week_start(utc(2026, 11, 25, 12, 0))) == "2026-11-22T21:00:00"


def test_savings_rate():
    assert periods.savings_rate(1000, 750) == 25
    assert periods.savings_rate(0, 50) is None


def _entry(user_id, amount, created_at, category="food", type_="expense"):
    entry_id = transactions.add_expense(user_id, amount, category, "", type_=type_)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", (created_at, entry_id))


def test_month_spending_in_summary_equals_budget_spending(fresh_db):
    init_db()
    # 31 Oct 21:30 UTC = 1 Nov 00:30 Nairobi -> counts in November.
    _entry(1, 100, "2026-10-31T21:30:00")
    # 31 Oct 20:30 UTC = 31 Oct 23:30 Nairobi -> October, excluded.
    _entry(1, 999, "2026-10-31T20:30:00")
    _entry(1, 50, "2026-11-20T09:00:00")
    since = periods.month_start(utc(2026, 11, 25, 12, 0))
    _, summary_total = summaries.summary_since(1, since, type_="expense")
    assert summary_total == 150
    assert budgets.month_total_for_category(1, "food", since) == summary_total
