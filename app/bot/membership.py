import html
import logging
from functools import wraps

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, ContextTypes, filters

from app.config import REQUIRED_CHANNEL, CHANNEL_INVITE_LINK
from app.services import users
from app.bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

VALID_STATUSES = {"member", "administrator", "creator"}


# ---------------------------------------------------------------------------
# Subscription gate
# ---------------------------------------------------------------------------
async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in VALID_STATUSES
    except Exception as e:
        logger.warning(f"Subscription check failed for {user_id}: {e}")
        return False


def gate_keyboard():
    buttons = []
    if CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton("📢 Join the channel", url=CHANNEL_INVITE_LINK)])
    buttons.append([InlineKeyboardButton("✅ I've subscribed", callback_data="recheck_sub")])
    return InlineKeyboardMarkup(buttons)


GATE_TEXT = (
    "🔒 <b>Welcome to your expense tracker!</b>\n\n"
    "Here's what I do:\n"
    "• Log spending in 3 taps\n"
    "• Warn you the moment you're near a budget\n"
    "• Send you a spending recap every Monday\n\n"
    "This bot is free — you just need to join my channel first:\n"
    f"{html.escape(CHANNEL_INVITE_LINK)}\n\n"
    "Then tap ✅ below."
)


async def send_gate(update: Update):
    await update.effective_message.reply_text(
        GATE_TEXT, reply_markup=gate_keyboard(), parse_mode=ParseMode.HTML
    )


def require_subscription(handler):
    """For simple, non-conversation button/command handlers."""
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user_id = update.effective_user.id
        if await is_subscribed(context, user_id):
            users.register_user(user_id)
            return await handler(update, context, *a, **kw)
        await send_gate(update)
    return wrapper


async def recheck_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_subscribed(context, user_id):
        users.register_user(user_id)
        await query.answer("You're in! 🎉")
        await query.edit_message_text("✅ Subscription confirmed! Here's your menu 👇")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Tap a button to get started.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("Still not subscribed — join the channel first.", show_alert=True)
