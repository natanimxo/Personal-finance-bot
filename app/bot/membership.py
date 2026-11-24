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
# Telegram's answers when the bot can't see a channel's members: it isn't an admin
# there, or isn't in the channel at all ("chat not found" for a channel it can't see).
# Either way it's our setup, not the user's fault, so the check lets them through.
NOT_ADMIN_ERRORS = ("member list is inaccessible", "not enough rights", "bot is not a member", "chat not found")


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

    def last_known(self, user_id) -> bool:
        """The last real answer; with none yet, the user is let through (an error never blocks)."""
        return self._last_known.get(user_id, True)

    def forget(self, user_id):
        self._subscribed_at.pop(user_id, None)
        self._last_known.pop(user_id, None)

    def clear(self):
        self._subscribed_at.clear()
        self._last_known.clear()


membership_cache = MembershipCache()


_alerted = set()   # (kind, chat_id) the admin has been told about in this run


async def _alert(bot, kind: str, chat_ids):
    """One alert per channel and problem per run: kind is not_admin or no_invite."""
    new = [c for c in chat_ids if (kind, c) not in _alerted]
    if not new:
        return
    _alerted.update((kind, c) for c in new)
    logger.error("Channel gate: %s in %s", kind, ", ".join(map(str, new)))
    if config.ADMIN_CHAT_ID is not None:
        try:
            await bot.send_message(chat_id=config.ADMIN_CHAT_ID,
                                   text=t(f"gate.alert_{kind}", channels=esc(", ".join(map(str, new)))))
        except Exception as e:
            logger.warning(f"Couldn't alert the admin: {e}")


async def check_access(bot, user_id: int, live: bool = False):
    """(allowed, position). position is None when nothing is required (gate off, the
    admin, free days). A cached "member" answer counts for 15 minutes; a "not a
    member" answer is never cached. Real answers are recorded (gate.observe)."""
    pos = await db_call(gate.position, user_id)
    if pos is None:
        return True, None
    key = (user_id, pos.channel.chat_id)
    if not live and membership_cache.fresh(key):
        return True, pos
    try:
        member = await bot.get_chat_member(pos.channel.chat_id, user_id)
    except Exception as e:
        if any(text in str(e).lower() for text in NOT_ADMIN_ERRORS):
            await _alert(bot, "not_admin", [pos.channel.chat_id])
            return True, pos   # our setup problem, not the user's
        fallback = membership_cache.last_known(key)
        logger.warning(f"Membership check in {pos.channel.chat_id} failed for {user_id}: {e}; "
                       f"using the last known result ({fallback})")
        return fallback, pos
    joined = counts_as_joined(member)
    membership_cache.store(key, joined)
    await db_call(gate.observe, user_id, pos, joined)
    return joined, pos


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int, live: bool = False) -> bool:
    """True when the user may go on: gate off, admin, free days, or in this period's channel."""
    return (await check_access(context.bot, user_id, live))[0]


async def channel_title(bot, channel) -> str:
    """The channel's current title from getChat (kept a day); never configured by hand."""
    if channel.title:
        return channel.title
    try:
        chat = await bot.get_chat(channel.chat_id)
    except Exception as e:
        logger.warning("getChat %s failed: %s", channel.chat_id, e)
        return channel.name
    await db_call(gate.cache_title, channel.chat_id, chat.title or str(channel.chat_id))
    return chat.title or channel.name


async def bot_rights(bot, chat_id: int):
    """(is admin, can invite users via link); either is None when Telegram doesn't say."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
    except Exception as e:
        if any(text in str(e).lower() for text in NOT_ADMIN_ERRORS):
            return False, False
        logger.warning("Admin check in %s failed: %s", chat_id, e)
        return None, None
    if me.status == "creator":
        return True, True
    if me.status != "administrator":
        return False, False
    return True, bool(getattr(me, "can_invite_users", False))


async def bot_is_admin(bot, chat_id: int):
    return (await bot_rights(bot, chat_id))[0]


async def ensure_invite_link(bot, channel):
    """The channel's one "Finance Bot" link: the stored one while it still works,
    else a new one (only when the old one was revoked or is gone). None if refused."""
    if channel.invite_link:
        try:
            link = await bot.edit_chat_invite_link(channel.chat_id, channel.invite_link, name=gate.INVITE_LINK_NAME)
            if not link.is_revoked:
                return channel.invite_link
        except Exception as e:
            logger.warning("Stored invite link for %s no longer works (%s): making a new one", channel.chat_id, e)
    try:
        link = await bot.create_chat_invite_link(channel.chat_id, name=gate.INVITE_LINK_NAME)
    except Exception as e:
        logger.warning("createChatInviteLink %s failed: %s", channel.chat_id, e)
        await db_call(gate.store_invite_link, channel.chat_id, None)
        return None
    await db_call(gate.store_invite_link, channel.chat_id, link.invite_link)
    return link.invite_link


async def check_channels(bot):
    """[{channel, title, admin, can_invite}] for every channel in the rotation."""
    rows = []
    for channel in await db_call(gate.channels):
        admin, can_invite = await bot_rights(bot, channel.chat_id)
        rows.append({"channel": channel, "title": await channel_title(bot, channel), "admin": admin,
                     "can_invite": can_invite})
    return rows


async def prepare(bot):
    """When the gate is turned on, and at startup while it is on: check the bot is an
    admin with the "Invite users via link" right in every channel, make sure each has
    its invite link, and alert the admin about any channel that fails."""
    rows = await check_channels(bot)
    for row in rows:
        row["link"] = await ensure_invite_link(bot, row["channel"]) if row["admin"] and row["can_invite"] else None
    not_admin = [r["channel"].chat_id for r in rows if r["admin"] is not True]
    no_invite = [r["channel"].chat_id for r in rows if r["admin"] is True and not r["link"]]
    for kind, ids in (("not_admin", not_admin), ("no_invite", no_invite)):
        _alerted.difference_update((kind, c) for c in ids)   # an explicit check always reports
        await _alert(bot, kind, ids)
    return rows


async def startup_check(bot):
    if not await db_call(gate.enabled):
        logger.info("Channel gate: off")
        return
    rows = await prepare(bot)
    logger.info("Channel gate: on, %d channel(s), all ready: %s", len(rows),
                all(r["admin"] and r["link"] for r in rows))


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A user joined or left one of the channels. It matters only for a user's
    current required channel: their cached answer is dropped (so the next action
    checks again) and the change is recorded."""
    change = update.chat_member
    user = change.new_chat_member.user
    was, now_in = counts_as_joined(change.old_chat_member), counts_as_joined(change.new_chat_member)
    if user.is_bot or was == now_in:
        return
    if await db_call(gate.channel_update, user.id, change.chat.id, now_in):
        membership_cache.forget((user.id, change.chat.id))


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
    if update.chat_member or update.my_chat_member:
        return  # someone joining / leaving a channel, not a user talking to the bot
    if user and not user.is_bot:
        await touch_user(user.id)
        # Looked up in a worker thread but set here, on the event loop, so it sticks.
        periods.set_zone(await db_call(periods.user_zone_name, user.id), user.id)
    else:
        periods.set_zone(periods.FALLBACK_ZONE)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
async def join_screen(bot, user_id: int, pos):
    """(text, keyboard) for the join screen, and records that it was shown."""
    title = await channel_title(bot, pos.channel)
    left = await db_call(gate.has_left, user_id, pos)
    # Only the channel's name ever reaches users: nothing about how the gate works.
    text = t("gate.text_left", name=esc(title)) if left else t("gate.text")
    buttons = []
    if pos.channel.invite_link:
        buttons.append([InlineKeyboardButton(t("gate.join", name=title), url=pos.channel.invite_link)])
    else:
        await _alert(bot, "no_invite", [pos.channel.chat_id])
    buttons.append([InlineKeyboardButton(t("gate.subscribed"), callback_data="recheck_sub")])
    await db_call(gate.record_shown, user_id, pos)
    return text, InlineKeyboardMarkup(buttons)


async def join_details(bot, user_id: int, pos) -> dict:
    """The Mini App's join screen, its texts straight from the strings file (and records
    that it was shown). Nothing about how the gate works, only the channel's name."""
    await db_call(gate.record_shown, user_id, pos)
    title = await channel_title(bot, pos.channel)
    left = await db_call(gate.has_left, user_id, pos)
    return {"title": t("gate.app_title"),
            "body": t("gate.text_left", name=title) if left else t("gate.app_body"),
            "join_link": pos.channel.invite_link or "", "join_button": t("gate.join", name=title),
            "joined_button": t("gate.subscribed"), "not_yet": t("gate.still_not"),
            "welcome": t("gate.confirmed")}


async def send_gate(update: Update, context=None):
    """The join screen: a welcome (or "you left"), 📢 Join <channel> and ✅ I've joined."""
    pos = await db_call(gate.position, update.effective_user.id)
    if pos is None:
        return
    text, kb = await join_screen(update.get_bot(), update.effective_user.id, pos)
    await update.effective_message.reply_text(text, reply_markup=kb)


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
