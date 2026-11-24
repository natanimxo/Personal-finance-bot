"""The channel gate's rules, without Telegram: which channels there are, and which
one (if any) a user has to be in right now.

- GATE_ENABLED=false (the default): no checks at all.
- GATE_CHANNELS: up to 6 channels, "@username|https://t.me/username" or
  "-1001234567890|https://t.me/+invite" for a private one, comma-separated.
  The older CHANNEL_ID / REQUIRED_CHANNEL with CHANNEL_LINK / CHANNEL_INVITE_LINK
  still work, as a list of one.
- A user's first FREE_DAYS days (from their first contact with the bot) are free.
  After that the required channel rotates every PERIOD_DAYS days, per user:
  days 31-60 channel 1, days 61-90 channel 2, ... and round again. Only the
  current period's channel is needed.
- ADMIN_CHAT_ID never needs a channel.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app import config
from app.db import get_conn

logger = logging.getLogger(__name__)

MAX_CHANNELS = 6
FREE_DAYS = 30
PERIOD_DAYS = 30
CHAT_ID = re.compile(r"^(@[A-Za-z][A-Za-z0-9_]{3,31}|-100\d{5,})$")


@dataclass(frozen=True)
class Channel:
    chat_id: str          # @username or -100... id, what getChatMember takes
    link: str             # where the Join button goes
    number: int           # 1-based position in the list

    @property
    def name(self) -> str:
        return self.chat_id if self.chat_id.startswith("@") else f"channel {self.number}"


def parse_channels(raw: str, legacy_id: str = "", legacy_link: str = ""):
    """(channels, problems). Bad entries are left out and described in `problems`."""
    entries, problems = [], []
    if raw.strip():
        for part in [p.strip() for p in raw.split(",") if p.strip()]:
            chat_id, _, link = (s.strip() for s in part.partition("|"))
            entries.append((chat_id, link))
    elif legacy_id:
        entries.append((legacy_id.strip(), legacy_link.strip()))
    channels = []
    for chat_id, link in entries:
        if not CHAT_ID.match(chat_id):
            problems.append(f"{chat_id!r} is not a channel id: use @username or the numeric -100... id "
                            "(an invite link goes after the |)")
            continue
        if len(channels) == MAX_CHANNELS:
            problems.append(f"only the first {MAX_CHANNELS} channels are used; {chat_id} is ignored")
            continue
        if not link and chat_id.startswith("@"):
            link = f"https://t.me/{chat_id[1:]}"
        channels.append(Channel(chat_id, link, len(channels) + 1))
    return channels, problems


def channels():
    found, _ = parse_channels(config.GATE_CHANNELS, config.REQUIRED_CHANNEL, config.CHANNEL_INVITE_LINK)
    return found


def problems():
    return parse_channels(config.GATE_CHANNELS, config.REQUIRED_CHANNEL, config.CHANNEL_INVITE_LINK)[1]


def enabled() -> bool:
    return bool(config.GATE_ENABLED and channels())


def is_exempt(user_id: int) -> bool:
    return config.ADMIN_CHAT_ID is not None and user_id == config.ADMIN_CHAT_ID


def days_since(first_start: str, now: datetime = None) -> int:
    """Whole days since the user's first contact (0 on the first day)."""
    now = now or datetime.now(timezone.utc)
    first = datetime.fromisoformat(first_start).replace(tzinfo=timezone.utc)
    return max(0, (now - first).days)


def channel_index_for(days: int, count: int):
    """None in the free period, else the 0-based channel for day `days` (0-based)."""
    if count == 0 or days < FREE_DAYS:
        return None
    return ((days - FREE_DAYS) // PERIOD_DAYS) % count


def first_start(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT first_start_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row["first_start_at"] if row and row["first_start_at"] else None


def required_channel(user_id: int, now: datetime = None):
    """The channel this user has to be in now, or None (gate off, admin, or free month)."""
    if not enabled() or is_exempt(user_id):
        return None
    listed = channels()
    started = first_start(user_id)
    days = days_since(started, now) if started else 0   # not registered yet: this is their first day
    index = channel_index_for(days, len(listed))
    return None if index is None else listed[index]


def stats(now: datetime = None) -> dict:
    """{"free": n, "channels": [n per channel]} over active users."""
    listed = channels()
    counts = {"free": 0, "channels": [0] * len(listed)}
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, first_start_at FROM users WHERE active = 1").fetchall()
    for r in rows:
        if is_exempt(r["user_id"]):
            continue
        index = channel_index_for(days_since(r["first_start_at"], now), len(listed)) if r["first_start_at"] else None
        if index is None:
            counts["free"] += 1
        else:
            counts["channels"][index] += 1
    return counts
