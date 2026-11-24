"""A gentle nudge towards the Mini App for people who log entries by hand in the chat.

After a user logs an entry in the bot (guided flow or quick entry) they get one short
message with an Open app button: after their first bot entry, then after every
HINT_EVERY-th one. Anyone who has ever opened the Mini App is never nudged, and
nothing is sent when the Mini App has no https address. It can never break logging.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.db import db_call
from app.services import users
from app.strings import t

logger = logging.getLogger(__name__)

HINT_EVERY = 10


def should_suggest(count: int, app_seen: bool) -> bool:
    return not app_seen and (count == 1 or count % HINT_EVERY == 0)


async def suggest_mini_app(bot, chat_id: int, user_id: int):
    """Call after an entry was logged in the bot."""
    try:
        from app.web.server import mini_app_url

        count, app_seen = await db_call(users.bot_entry_logged, user_id)
        url = mini_app_url()
        if not url or not should_suggest(count, app_seen):
            return
        await bot.send_message(
            chat_id=chat_id, text=t("hint.mini_app"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t("hint.open_app"), web_app=WebAppInfo(url=url))]]),
        )
    except Exception as e:  # a tip is never worth an error
        logger.warning("Mini App suggestion failed for %s: %s", user_id, e)
