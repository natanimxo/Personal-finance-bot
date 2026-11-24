"""Week and month boundaries, in APP_TIMEZONE. Summary, budgets and the recap all use these.

created_at is stored as naive UTC ISO text (naive UTC from datetime.now(timezone.utc)), so a
boundary is converted with to_db() before it is compared in SQL.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import config


def tz() -> ZoneInfo:
    return ZoneInfo(config.APP_TIMEZONE)


def now_local(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(tz())


def week_start(now: datetime = None) -> datetime:
    """Monday 00:00 of the current week, local time."""
    local = now_local(now)
    monday = local - timedelta(days=local.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: datetime = None) -> datetime:
    """The 1st of the current month at 00:00, local time."""
    return now_local(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def previous_week(now: datetime = None):
    """(start, end) of last Monday-to-Sunday week; end is exclusive."""
    end = week_start(now)
    return end - timedelta(days=7), end


def to_db(moment: datetime) -> str:
    """An aware datetime as the naive UTC ISO text that created_at is stored in."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz())
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def savings_rate(income: float, expenses: float):
    """Net as a percentage of income, or None when there is no income."""
    if not income:
        return None
    return (income - expenses) / income * 100
