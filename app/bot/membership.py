"""The channel-membership gate, with a short cache so 1,000 users don't mean
1,000 getChatMember calls a minute."""
import logging
import time
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app import config
from app.bot.keyboards import esc, main_menu_keyboard
from app.db import db_call
from app.services import users

logger = logging.getLogger(__name__)

VALID_STATUSES = {"member", "administrator", "creator"}
CACHE_SECONDS = 15 * 60


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


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int, live: bool = False) -> bool:
    if not live and membership_cache.fresh(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(config.REQUIRED_CHANNEL, user_id)
    except Exception as e:
        fallback = membership_cache.last_known(user_id)
        logger.warning(f"Subscription check failed for {user_id}: {e}; using last known result ({fallback})")
        return fallback
    subscribed = member.status in VALID_STATUSES
    membership_cache.store(user_id, subscribed)
    return subscribed


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
    """Runs before every other handler (group -1)."""
    if update.effective_user and not update.effective_user.is_bot:
        await touch_user(update.effective_user.id)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
def gate_keyboard():
    buttons = []
    if config.CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton("📢 Join the channel", url=config.CHANNEL_INVITE_LINK)])
    buttons.append([InlineKeyboardButton("✅ I've subscribed", callback_data="recheck_sub")])
    return InlineKeyboardMarkup(buttons)


def gate_text() -> str:
    return (
        "🔒 <b>Welcome to your expense tracker!</b>\n\n"
        "Here's what I do:\n"
        "• Log spending in 3 taps\n"
        "• Warn you the moment you're near a budget\n"
        "• Send you a spending recap every Monday\n\n"
        "This bot is free — you just need to join my channel first:\n"
        f"{esc(config.CHANNEL_INVITE_LINK)}\n\n"
        "Then tap ✅ below."
    )


async def send_gate(update: Update):
    await update.effective_message.reply_text(gate_text(), reply_markup=gate_keyboard())


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
        await query.answer("You're in! 🎉")
        await query.edit_message_text("✅ Subscription confirmed! Here's your menu 👇")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Tap a button to get started.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("Still not subscribed — join the channel first.", show_alert=True)
