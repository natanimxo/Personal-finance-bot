"""The channel gate's rules, without Telegram.

Everything lives in the database and is managed by the admin from the bot
(/gate_add, /gate_remove, /gate_list, /gate_on, /gate_off):

- gate_settings.enabled: off ("0") until /gate_on. While off, nobody is checked.
- gate_channels: the rotation, by numeric chat id only (a renamed channel or bot
  breaks nothing). Titles and invite links are fetched from Telegram and cached
  here for CACHE_HOURS; they are never configured by hand.
- Each user rotates on their own clock, from their first contact with the bot:
  days 1-30 the first channel, days 31-60 the second, ... and round the list
  again. Only the current channel is needed.
- ADMIN_CHAT_ID is never checked.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config
from app.db import get_conn

MAX_CHANNELS = 6
FREE_DAYS = 0      # no free period: day 1 already needs the first channel
PERIOD_DAYS = 30
CACHE_HOURS = 24


@dataclass(frozen=True)
class Channel:
    chat_id: int          # numeric, e.g. -1001897854375
    number: int           # 1-based place in the rotation
    title: str = None     # cached from getChat
    invite_link: str = None   # cached from createChatInviteLink

    @property
    def name(self) -> str:
        return self.title or f"channel {self.number}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime = None) -> str:
    return (moment or _now()).replace(tzinfo=None).isoformat(timespec="seconds")


def _fresh(stamp: str, now: datetime = None) -> bool:
    if not stamp:
        return False
    at = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    return (now or _now()) - at < timedelta(hours=CACHE_HOURS)


# --- on / off ------------------------------------------------------------------------------
def is_on() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM gate_settings WHERE key = 'enabled'").fetchone()
    return bool(row and row["value"] == "1")


def set_on(on: bool):
    with get_conn() as conn:
        conn.execute("INSERT INTO gate_settings (key, value) VALUES ('enabled', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("1" if on else "0",))


def enabled() -> bool:
    """On, and there is at least one channel to require."""
    return is_on() and bool(channels())


# --- the channel list ------------------------------------------------------------------------
def channels(now: datetime = None):
    """The rotation in order, with whatever title / link is still fresh in the cache."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM gate_channels ORDER BY position, added_at").fetchall()
    return [Channel(r["chat_id"], i,
                    r["title"] if _fresh(r["title_at"], now) else None,
                    r["invite_link"] if _fresh(r["invite_link_at"], now) else None)
            for i, r in enumerate(rows, 1)]


class GateError(ValueError):
    pass


def check_chat_id(chat_id) -> int:
    """Only numeric channel ids (-100...) are stored."""
    try:
        value = int(str(chat_id).strip())
    except ValueError:
        raise GateError("not_numeric")
    if not str(value).startswith("-100"):
        raise GateError("not_numeric")
    return value


def add_channel(chat_id) -> Channel:
    """Add to the end of the rotation."""
    chat_id = check_chat_id(chat_id)
    current = channels()
    if any(c.chat_id == chat_id for c in current):
        raise GateError("already")
    if len(current) >= MAX_CHANNELS:
        raise GateError("full")
    with get_conn() as conn:
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM gate_channels").fetchone()[0]
        conn.execute("INSERT INTO gate_channels (chat_id, position, added_at) VALUES (?, ?, ?)",
                     (chat_id, position, _stamp()))
    return channels()[-1]


def remove_channel(number: int) -> Channel:
    """Remove the n-th channel (1-based); the ones after it move up."""
    current = channels()
    if not 1 <= number <= len(current):
        raise GateError("no_such")
    gone = current[number - 1]
    with get_conn() as conn:
        conn.execute("DELETE FROM gate_channels WHERE chat_id = ?", (gone.chat_id,))
        for i, c in enumerate([c for c in current if c.chat_id != gone.chat_id], 1):
            conn.execute("UPDATE gate_channels SET position = ? WHERE chat_id = ?", (i, c.chat_id))
    return gone


def cache_title(chat_id: int, title: str):
    with get_conn() as conn:
        conn.execute("UPDATE gate_channels SET title = ?, title_at = ? WHERE chat_id = ?", (title, _stamp(), chat_id))


def cache_invite_link(chat_id: int, link: str):
    with get_conn() as conn:
        conn.execute("UPDATE gate_channels SET invite_link = ?, invite_link_at = ? WHERE chat_id = ?",
                     (link, _stamp(), chat_id))


# --- who needs which channel ------------------------------------------------------------------
def is_exempt(user_id: int) -> bool:
    return config.ADMIN_CHAT_ID is not None and user_id == config.ADMIN_CHAT_ID


def days_since(first_start: str, now: datetime = None) -> int:
    """Whole days since the user's first contact (0 on the first day)."""
    first = datetime.fromisoformat(first_start).replace(tzinfo=timezone.utc)
    return max(0, ((now or _now()) - first).days)


def channel_index_for(days: int, count: int):
    """None during a free period (none by default), else the 0-based channel for day `days`."""
    if count == 0 or days < FREE_DAYS:
        return None
    return ((days - FREE_DAYS) // PERIOD_DAYS) % count


def first_start(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT first_start_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row["first_start_at"] if row and row["first_start_at"] else None


def required_channel(user_id: int, now: datetime = None):
    """The channel this user has to be in now, or None (gate off, no channels, or the admin)."""
    if is_exempt(user_id) or not is_on():
        return None
    listed = channels(now)
    started = first_start(user_id)
    index = channel_index_for(days_since(started, now) if started else 0, len(listed))
    return None if index is None else listed[index]


def stats(now: datetime = None) -> dict:
    """{"free": n, "channels": [n per channel]} over active users (the admin left out)."""
    listed = channels(now)
    counts = {"free": 0, "channels": [0] * len(listed)}
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, first_start_at FROM users WHERE active = 1").fetchall()
    for r in rows:
        if is_exempt(r["user_id"]):
            continue
        days = days_since(r["first_start_at"], now) if r["first_start_at"] else 0
        index = channel_index_for(days, len(listed))
        if index is None:
            counts["free"] += 1
        else:
            counts["channels"][index] += 1
    return counts
