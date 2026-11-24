"""The channel gate's rules and records, without Telegram.

Everything lives in the database and is managed by the admin from the bot
(/gate_add, /gate_remove, /gate_list, /gate_on, /gate_off, /gate_status,
/gate_stats):

- gate_settings.enabled: off ("0") until /gate_on. While off, nobody is checked.
- gate_channels: the rotation, by numeric chat id only (renaming a channel or the
  bot breaks nothing). Titles are fetched with getChat and cached for a day; each
  channel has one permanent "Finance Bot" invite link, made when the gate is
  turned on and replaced only if it gets revoked.
- One schedule for everyone, no free period: gate_settings.start_at and
  start_channel. Period n = floor((now - start_at) / 30 days); its channel is the
  one n places after the start channel in the list order, round again. Every user,
  old or new, needs the same channel at the same moment. Only the current period's
  channel is ever checked; earlier ones don't matter any more.
- During a period the user must stay in that period's channel. Leaving it shows
  the join screen at their next action ("You left ..."), never mid-action.
- ADMIN_CHAT_ID is never checked.

gate_events counts what the gate does, only ever for the user's required channel
at that moment: shown (join screen displayed), joined_via_bot (not a member when
first checked this period, a member afterwards), already_member (a member the
first time they were checked), left, rejoined.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config
from app.db import get_conn

MAX_CHANNELS = 6
PERIOD_DAYS = 30
TITLE_CACHE_HOURS = 24
INVITE_LINK_NAME = "Finance Bot"
EVENTS = ("shown", "joined_via_bot", "already_member", "left", "rejoined")


@dataclass(frozen=True)
class Channel:
    chat_id: int              # numeric, e.g. -1001897854375
    number: int               # 1-based place in the rotation
    title: str = None         # cached from getChat (a day)
    invite_link: str = None   # the stored "Finance Bot" link, if made yet

    @property
    def name(self) -> str:
        return self.title or f"channel {self.number}"


@dataclass(frozen=True)
class Position:
    """A period of the shared schedule: its number, channel, dates and the next channel."""
    period: int               # global period n: 0 from the start date, then 1, 2, ...
    channel: Channel
    days_left: int            # whole days until it ends, rounded up
    starts_at: datetime = None
    ends_at: datetime = None
    next_channel: Channel = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime = None) -> str:
    return (moment or _now()).replace(tzinfo=None).isoformat(timespec="seconds")


def _fresh(stamp: str, hours: int, now: datetime = None) -> bool:
    if not stamp:
        return False
    at = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    return (now or _now()) - at < timedelta(hours=hours)


# --- on / off ------------------------------------------------------------------------------------
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


# --- the channel list ------------------------------------------------------------------------------
def channels(now: datetime = None):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM gate_channels ORDER BY position, added_at").fetchall()
    return [Channel(r["chat_id"], i, r["title"] if _fresh(r["title_at"], TITLE_CACHE_HOURS, now) else None,
                    r["invite_link"])
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
        position_ = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM gate_channels").fetchone()[0]
        conn.execute("INSERT INTO gate_channels (chat_id, position, added_at) VALUES (?, ?, ?)",
                     (chat_id, position_, _stamp()))
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


def note_bot(bot_id: int) -> bool:
    """Remember which bot the stored invite links belong to. A link only works for the
    bot that made it, so when the bot changes (a new token) every stored link is
    forgotten and the new bot makes its own. True when links were cleared."""
    stored = _setting("bot_id")
    if stored == str(bot_id):
        return False
    with get_conn() as conn:
        conn.execute("INSERT INTO gate_settings (key, value) VALUES ('bot_id', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(bot_id),))
        conn.execute("UPDATE gate_channels SET invite_link = NULL, invite_link_at = NULL")
    return True


def cache_title(chat_id: int, title: str):
    with get_conn() as conn:
        conn.execute("UPDATE gate_channels SET title = ?, title_at = ? WHERE chat_id = ?", (title, _stamp(), chat_id))


def store_invite_link(chat_id: int, link):
    with get_conn() as conn:
        conn.execute("UPDATE gate_channels SET invite_link = ?, invite_link_at = ? WHERE chat_id = ?",
                     (link, _stamp() if link else None, chat_id))


# --- the schedule: one for everyone ----------------------------------------------------------------
def is_exempt(user_id: int) -> bool:
    return config.ADMIN_CHAT_ID is not None and user_id == config.ADMIN_CHAT_ID


def _setting(key: str):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM gate_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def schedule_start():
    """(start moment, start channel id) of the shared schedule."""
    start = datetime.fromisoformat(_setting("start_at") or "2026-11-23T21:00:00").replace(tzinfo=timezone.utc)
    channel = _setting("start_channel")
    return start, int(channel) if channel else None


def set_schedule(start_at: datetime, start_channel: int):
    with get_conn() as conn:
        for key, value in (("start_at", _stamp(start_at)), ("start_channel", str(start_channel))):
            conn.execute("INSERT INTO gate_settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def period_number(now: datetime = None) -> int:
    """n = floor((now - start) / 30 days); 0 before and during the first period."""
    start, _ = schedule_start()
    return max(0, ((now or _now()) - start) // timedelta(days=PERIOD_DAYS))


def period_at(n: int, now: datetime = None, listed=None):
    """Position for global period n: its channel (n places after the start channel,
    round the list), its dates, the days left (from `now`) and the next channel."""
    listed = listed if listed is not None else channels(now)
    if not listed:
        return None
    start, start_channel = schedule_start()
    ids = [c.chat_id for c in listed]
    first = ids.index(start_channel) if start_channel in ids else 0
    channel = listed[(first + n) % len(listed)]
    following = listed[(first + n + 1) % len(listed)]
    starts = start + timedelta(days=PERIOD_DAYS * n)
    ends = starts + timedelta(days=PERIOD_DAYS)
    remaining = ends - (now or _now())
    days_left = max(0, -(-remaining // timedelta(days=1)))   # whole days, rounded up
    return Position(n, channel, days_left, starts, ends, following)


def current(now: datetime = None):
    """The period everyone is in now, or None (no channels)."""
    return period_at(period_number(now), now)


def upcoming(count: int = 6, now: datetime = None):
    """The current period and the ones after it."""
    listed = channels(now)
    n = period_number(now)
    return [period_at(n + i, now, listed) for i in range(count)] if listed else []


def position(user_id: int, now: datetime = None):
    """What this user must be in now, or None (gate off, the admin, no channels)."""
    if is_exempt(user_id) or not is_on():
        return None
    return current(now)


def required_channel(user_id: int, now: datetime = None):
    found = position(user_id, now)
    return found.channel if found else None


# --- what happened: per-period state and events -----------------------------------------------------
def _event(conn, user_id, channel_id, period, event, now):
    conn.execute("INSERT INTO gate_events (user_id, channel_id, period_number, event, at) VALUES (?, ?, ?, ?, ?)",
                 (user_id, channel_id, period, event, _stamp(now)))


def _state(conn, user_id, period):
    return conn.execute("SELECT * FROM gate_user_periods WHERE user_id = ? AND period_number = ?",
                        (user_id, period)).fetchone()


def has_left(user_id: int, pos: Position) -> bool:
    """Was the user in this period's channel at some point, and isn't any more?"""
    with get_conn() as conn:
        state = _state(conn, user_id, pos.period)
        if state is None or state["channel_id"] != pos.channel.chat_id or state["member_now"]:
            return False
        return bool(conn.execute(
            "SELECT 1 FROM gate_events WHERE user_id = ? AND period_number = ? AND channel_id = ? "
            "AND event = 'left' LIMIT 1", (user_id, pos.period, pos.channel.chat_id)).fetchone())


def observe(user_id: int, pos: Position, is_member: bool, now: datetime = None):
    """Record a real membership answer for the user's current channel (not a cached
    one). The first answer of a period decides already_member (a member) or not; a
    change after that is joined_via_bot / rejoined, or left."""
    chat_id = pos.channel.chat_id
    with get_conn() as conn:
        state = _state(conn, user_id, pos.period)
        if state is None or state["channel_id"] != chat_id:   # first check this period (or the list changed)
            conn.execute(
                "INSERT OR REPLACE INTO gate_user_periods (user_id, period_number, channel_id, first_seen_at, "
                "member_at_first, member_now) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, pos.period, chat_id, _stamp(now), int(is_member), int(is_member)))
            if is_member:
                _event(conn, user_id, chat_id, pos.period, "already_member", now)
            return
        if bool(state["member_now"]) == is_member:
            return
        conn.execute("UPDATE gate_user_periods SET member_now = ? WHERE user_id = ? AND period_number = ?",
                     (int(is_member), user_id, pos.period))
        if not is_member:
            _event(conn, user_id, chat_id, pos.period, "left", now)
            return
        left_before = conn.execute(
            "SELECT 1 FROM gate_events WHERE user_id = ? AND period_number = ? AND channel_id = ? "
            "AND event = 'left' LIMIT 1", (user_id, pos.period, chat_id)).fetchone()
        _event(conn, user_id, chat_id, pos.period, "rejoined" if left_before else "joined_via_bot", now)


def record_shown(user_id: int, pos: Position, now: datetime = None):
    with get_conn() as conn:
        _event(conn, user_id, pos.channel.chat_id, pos.period, "shown", now)


def channel_update(user_id: int, chat_id: int, is_member: bool, now: datetime = None) -> bool:
    """A chat_member update from a channel. It counts only for the user's current
    required channel; returns True when it was (the caller then drops the cached answer)."""
    pos = position(user_id, now)
    if pos is None or pos.channel.chat_id != chat_id:
        return False   # another period's channel: leaving or joining it changes nothing
    with get_conn() as conn:
        seen = _state(conn, user_id, pos.period)
    if seen is not None:
        observe(user_id, pos, is_member, now)
    return True


# --- numbers for /gate_status and /gate_stats ------------------------------------------------------
def stats(days: int = None, now: datetime = None) -> dict:
    """{"current": the current Position, "channels": [per channel: required (users who
    must be in it now: everyone but the admin, for the current channel), shown,
    joined_via_bot, already_member, left, rejoined (distinct users, within the last
    `days` days when given), subscribed (in it now this period, as last seen)]}."""
    now = now or _now()
    listed = channels(now)
    per = [dict(channel=c, required=0, subscribed=0, **{e: 0 for e in EVENTS}) for c in listed]
    by_id = {row["channel"].chat_id: row for row in per}
    pos = period_at(period_number(now), now, listed) if listed else None
    with get_conn() as conn:
        if pos:
            active = [r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE active = 1")
                      if not is_exempt(r["user_id"])]
            by_id[pos.channel.chat_id]["required"] = len(active)
            by_id[pos.channel.chat_id]["subscribed"] = conn.execute(
                "SELECT COUNT(*) FROM gate_user_periods WHERE period_number = ? AND channel_id = ? AND member_now = 1",
                (pos.period, pos.channel.chat_id)).fetchone()[0]
        since = _stamp(now - timedelta(days=days)) if days else "0000"
        for r in conn.execute("SELECT channel_id, event, COUNT(DISTINCT user_id) AS n FROM gate_events "
                              "WHERE at >= ? GROUP BY channel_id, event", (since,)):
            if r["channel_id"] in by_id and r["event"] in EVENTS:
                by_id[r["channel_id"]][r["event"]] = r["n"]
    return {"current": pos, "channels": per}
