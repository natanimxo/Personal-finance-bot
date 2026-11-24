"""The bot's command list (the "/" menu in Telegram), set at every start with setMyCommands.

Everyone gets the user commands; the admin's own chat also gets the admin ones.
Descriptions live in app/strings.py (cmd.*).
"""
import logging

from telegram import BotCommand, BotCommandScopeChat

from app import config
from app.strings import t

logger = logging.getLogger(__name__)

USER_COMMANDS = ["start", "help", "settings", "export", "cancel"]
ADMIN_COMMANDS = ["recap_now", "backup_now", "gate_status", "gate_list", "gate_schedule", "gate_stats", "gate_add",
                  "gate_remove", "gate_on", "gate_off"]


def _describe(names):
    return [BotCommand(name, t(f"cmd.{name}")) for name in names]


async def set_commands(bot):
    """Default list for everyone; the admin chat gets the longer one."""
    await bot.set_my_commands(_describe(USER_COMMANDS))
    if config.ADMIN_CHAT_ID is not None:
        await bot.set_my_commands(_describe(USER_COMMANDS + ADMIN_COMMANDS),
                                  scope=BotCommandScopeChat(chat_id=config.ADMIN_CHAT_ID))
    logger.info("Command list set (%d for everyone%s)", len(USER_COMMANDS),
                f", {len(ADMIN_COMMANDS)} more for the admin" if config.ADMIN_CHAT_ID is not None else "")
