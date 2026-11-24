"""The channel gate on the bot side: asking Telegram whether a user is in the
channel the rules in app/services/gate.py require now, with a short cache so
1,000 users don't mean 1,000 getChatMember calls a minute.

The gate is checked only when a user starts something (a menu screen, a command,
the start of an add flow, a quick entry, a Mini App request), never in the middle
of an entry. Telegram only answers getChatMember for a channel when the bot is an
administrator there; if it isn't, the check lets users through (and alerts the
admin) rather than locking everyone out.
"""
import logging
import time
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import config
from app.bot.keyboards import esc, main_menu_keyboard
from app.db import db_call
from app.services import gate, periods, prefs, users
from app.strings import t

logger = logging.getLogger(__name__)

# Counts as "in the channel". A restricted user is still a member if is_member is true.
JOINED_STATUSES = {"creator", "administrator", "member"}
CACHE_SECONDS = 15 * 60
# Telegram's answer when the bot can't see the member list: the bot isn't an admin.
NOT_ADMIN_ERRORS = ("member list is inaccessible", "not enough rights", "bot is not a member")


def counts_as_joined(member) -> bool:
    if member.status in JOINED_STATUSES:
        return True
    return member.status == "restricted" and bool(getattr(member, "is_member", False))


class MembershipCache:
    """Remembers "is subscribed" for CACHE_SECONDS. A "not subscribed" answer is
    never cached (joining takes effect at once), but every answer is kept as the
    last known result, used only when Telegram itself fails to answer."""

    def __init__(self, ttl: float = CACHE_SECONDS, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._subscribed_at = {}   # user_id -> time of the last positive check
        self._last_known = {}      # user_id -> bool

    def fresh(self, user_id: int) -> bool:
        at = self._subscribed_at.get(user_id)
        return at is not None and self.clock() - at < self.ttl

    def store(self, user_id: int, subscribed: bool):
        self._last_known[user_id] = subscribed
        if subscribed:
            self._subscribed_at[user_id] = self.clock()
        else:
            self._subscribed_at.pop(user_id, None)

    def last_known(self, user_id: int) -> bool:
        return self._last_known.get(user_id, False)

    def clear(self):
        self._subscribed_at.clear()
        self._last_known.clear()


membership_cache = MembershipCache()


_not_admin_alerted = set()   # channels the admin has been told about in this run
_titles = {}                 # chat_id -> channel title, filled by check_channels()


async def _alert_not_admin(bot, channel):
    if channel.chat_id in _not_admin_alerted:
        return
    _not_admin_alerted.add(channel.chat_id)
    logger.error("The bot is not an admin of %s, so it can't check members: letting users through", channel.chat_id)
    if config.ADMIN_CHAT_ID is not None:
        try:
            await bot.send_message(chat_id=config.ADMIN_CHAT_ID,
                                   text=t("gate.alert_not_admin", channels=esc(channel.chat_id)))
        except Exception as e:
            logger.warning(f"Couldn't alert the admin: {e}")


async def is_member_of(bot, channel, user_id: int, live: bool = False) -> bool:
    key = (user_id, channel.chat_id)
    if not live and membership_cache.fresh(key):
        return True
    try:
        member = await bot.get_chat_member(channel.chat_id, user_id)
    except Exception as e:
        if any(text in str(e).lower() for text in NOT_ADMIN_ERRORS):
            await _alert_not_admin(bot, channel)
            return True  # our setup problem, not the user's
        fallback = membership_cache.last_known(key)
        logger.warning(f"Membership check in {channel.chat_id} failed for {user_id}: {e}; "
                       f"using last known result ({fallback})")
        return fallback
    joined = counts_as_joined(member)
    membership_cache.store(key, joined)
    return joined


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int, live: bool = False) -> bool:
    """True when the user may go on: gate off, admin, free month, or in this month's channel."""
    channel = await db_call(gate.required_channel, user_id)
    if channel is None:
        return True
    return await is_member_of(context.bot, channel, user_id, live)


def channel_name(channel) -> str:
    return _titles.get(channel.chat_id) or channel.name


async def check_channels(bot):
    """[{channel, title, admin (True/False/None if unknown), error}] for every listed channel."""
    results = []
    for channel in gate.channels():
        row = {"channel": channel, "title": _titles.get(channel.chat_id), "admin": None, "error": ""}
        try:
            chat = await bot.get_chat(channel.chat_id)
            row["title"] = _titles[channel.chat_id] = chat.title or channel.chat_id
        except Exception as e:
            row["error"] = str(e)
        try:
            me = await bot.get_chat_member(channel.chat_id, bot.id)
            row["admin"] = me.status in ("administrator", "creator")
        except Exception as e:
            if any(text in str(e).lower() for text in NOT_ADMIN_ERRORS):
                row["admin"] = False
            row["error"] = row["error"] or str(e)
        results.append(row)
    return results


async def startup_check(bot):
    """On startup, with the gate on: tell the admin about any channel the bot isn't an admin of."""
    for problem in gate.problems():
        logger.error("GATE_CHANNELS: %s", problem)
    if not gate.enabled():
        logger.info("Channel gate: off")
        return
    rows = await check_channels(bot)
    missing = [r["channel"].chat_id for r in rows if r["admin"] is not True]
    logger.info("Channel gate: on, %d channel(s); bot not admin in: %s", len(rows), ", ".join(missing) or "none")
    if missing and config.ADMIN_CHAT_ID is not None:
        _not_admin_alerted.update(missing)
        try:
            await bot.send_message(chat_id=config.ADMIN_CHAT_ID,
                                   text=t("gate.alert_not_admin", channels=esc(", ".join(missing))))
        except Exception as e:
            logger.warning(f"Couldn't alert the admin: {e}")


# ---------------------------------------------------------------------------
# Active users: a user who blocked the bot is marked inactive (by the recap);
# the next update from them marks them active again.
# ---------------------------------------------------------------------------
_known_active = set()


async def touch_user(user_id: int):
    """Register the user / mark them active, at most one database write per process run."""
    if user_id in _known_active:
        return
    await db_call(users.register_user, user_id)
    _known_active.add(user_id)


def forget_active(user_id: int):
    _known_active.discard(user_id)


async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before every other handler (group -2): marks the sender active, and makes
    their own timezone the one used for the rest of this update."""
    user = update.effective_user
    if user and not user.is_bot:
        await touch_user(user.id)
        # Looked up in a worker thread but set here, on the event loop, so it sticks.
        periods.set_zone(await db_call(periods.user_zone_name, user.id), user.id)
    else:
        periods.set_zone(periods.FALLBACK_ZONE)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
def gate_keyboard(channel):
    buttons = []
    if channel.link:
        buttons.append([InlineKeyboardButton(t("gate.join", name=channel_name(channel)), url=channel.link)])
    buttons.append([InlineKeyboardButton(t("gate.subscribed"), callback_data="recheck_sub")])
    return InlineKeyboardMarkup(buttons)


def gate_text(channel) -> str:
    return t("gate.text", name=esc(channel_name(channel)), link=esc(channel.link or channel.chat_id))


async def send_gate(update: Update):
    channel = await db_call(gate.required_channel, update.effective_user.id)
    if channel is None:
        return
    await update.effective_message.reply_text(gate_text(channel), reply_markup=gate_keyboard(channel))


def require_subscription(handler):
    """For simple, non-conversation button/command handlers."""
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user_id = update.effective_user.id
        if await is_subscribed(context, user_id):
            await touch_user(user_id)
            return await handler(update, context, *a, **kw)
        await send_gate(update)
    return wrapper


async def recheck_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_subscribed(context, user_id, live=True):
        await touch_user(user_id)
        await query.answer(t("gate.youre_in"))
        p = await db_call(prefs.get_prefs, user_id)
        if not p["onboarded"]:  # a new user: currency and timezone first
            from app.bot.onboarding import begin

            await query.edit_message_reply_markup(reply_markup=None)
            await begin(context, update.effective_chat.id, p)
            return
        await query.edit_message_text(t("gate.confirmed"))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t("gate.get_started"),
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer(t("gate.still_not"), show_alert=True)
