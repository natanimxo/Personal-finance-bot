"""Week and month boundaries in the *user's* timezone. Summary, budgets, the recap
and recurring entries all use these.

Each user picks a timezone when they start (stored in user_prefs.timezone). The
zone in force is a context variable: the bot sets it for the user behind each
update, the API for the user behind each request, and jobs for each user they
handle. Service functions that take a user_id are wrapped with @in_user_zone, so
they use that user's zone whoever calls them. With no user (a server job such as
the backup) the zone is UTC.

occurred_at and created_at are stored as naive UTC ISO text, so a boundary is
converted with to_db() before it is compared in SQL.
"""
import functools
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FALLBACK_ZONE = "UTC"

# (user_id or None, IANA zone name) currently in force.
_zone: ContextVar = ContextVar("zone", default=(None, FALLBACK_ZONE))


def tz() -> ZoneInfo:
    return ZoneInfo(_zone.get()[1])


def zone_name() -> str:
    return _zone.get()[1]


def set_zone(name: str, user_id: int = None):
    """Make `name` the zone for the rest of this task (or thread). Returns a reset token."""
    return _zone.set((user_id, name or FALLBACK_ZONE))


@contextmanager
def use_zone(name: str, user_id: int = None):
    token = set_zone(name, user_id)
    try:
        yield
    finally:
        _zone.reset(token)


def user_zone_name(user_id: int) -> str:
    """The user's saved timezone, or UTC if they haven't picked one."""
    from app.db import get_conn

    with get_conn() as conn:
        row = conn.execute("SELECT timezone FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return (row["timezone"] if row and row["timezone"] else None) or FALLBACK_ZONE


def activate_user(user_id: int) -> str:
    """Bot and API: this update / request is the user's, so use their zone from here on."""
    name = user_zone_name(user_id)
    set_zone(name, user_id)
    return name


@contextmanager
def for_user(user_id: int):
    """The user's zone for the duration (a no-op when it is already in force)."""
    if _zone.get()[0] == user_id:
        yield
        return
    with use_zone(user_zone_name(user_id), user_id):
        yield


def in_user_zone(fn):
    """For service functions whose first argument is a user_id."""
    @functools.wraps(fn)
    def wrapper(user_id, *args, **kwargs):
        with for_user(user_id):
            return fn(user_id, *args, **kwargs)
    return wrapper


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


def previous_month(now: datetime = None):
    """(start, end) of last calendar month; end is exclusive."""
    end = month_start(now)
    start = (end - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, end


def to_db(moment: datetime) -> str:
    """An aware datetime as the naive UTC ISO text that dates are stored in."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz())
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def savings_rate(income: float, expenses: float):
    """Net as a percentage of income, or None when there is no income."""
    if not income:
        return None
    return (income - expenses) / income * 100


def today(now: datetime = None) -> date:
    return now_local(now).date()


def occurred_at_for(day, now: datetime = None) -> str:
    """Stored occurred_at for a local date: now if it's today, else that day at 12:00
    local (midday keeps it inside the day whatever the timezone)."""
    if day is None or day == today(now):
        return to_db(now_local(now))
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return to_db(datetime(day.year, day.month, day.day, 12, tzinfo=tz()))


def local_date_of(stored: str) -> date:
    """The local date of a stored naive-UTC timestamp."""
    return datetime.fromisoformat(stored).replace(tzinfo=timezone.utc).astimezone(tz()).date()


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_user_date(text: str, now: datetime = None) -> date:
    """today, yesterday, 2026-11-22, 22/11, 22/11/2026, 22-11, 22 Nov, Nov 22. Raises ValueError."""
    t = (text or "").strip().lower()
    base = today(now)
    if t in ("today", "now"):
        return base
    if t == "yesterday":
        return base - timedelta(days=1)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            return date.fromisoformat(t)
        m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", t)
        if m:
            year = int(m.group(3)) if m.group(3) else base.year
            year = year + 2000 if year < 100 else year
            d = date(year, int(m.group(2)), int(m.group(1)))
            # "22/12" typed in January means last December
            return d.replace(year=d.year - 1) if not m.group(3) and d > base else d
        m = re.fullmatch(r"(\d{1,2})\s+([a-z]{3})[a-z]*\.?(?:\s+(\d{4}))?|([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?", t)
        if m:
            day_, mon, yr = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
            d = date(int(yr) if yr else base.year, MONTHS[mon], int(day_))
            return d.replace(year=d.year - 1) if not yr and d > base else d
    except (KeyError, ValueError):
        pass
    from app.strings import t

    raise ValueError(t("error.date_format"))
