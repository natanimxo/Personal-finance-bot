"""Admin commands for the channel gate (ADMIN_CHAT_ID only; anyone else gets no reply).

    /gate_add      reply to a post forwarded from the channel (or /gate_add -100...)
    /gate_remove n take channel n out of the rotation
    /gate_list     the rotation: order, title, whether the bot is admin, users on each
    /gate_status   the same, plus on / off
    /gate_on       start checking
    /gate_off      stop checking

Channels are stored by numeric id only. The bot must be an admin of a channel to
add it: Telegram only shows a channel's members to its admins.
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.handlers import is_admin
from app.bot.keyboards import esc
from app.bot.membership import alert_missing_admin, bot_is_admin, channel_title, check_channels
from app.db import db_call
from app.services import gate
from app.strings import t

ADMIN_MARK = {True: "gate.admin_yes", False: "gate.admin_no", None: "gate.admin_unknown"}


def forwarded_chat_id(message):
    """The channel a replied-to post was forwarded from, if any."""
    original = message.reply_to_message if message else None
    if original is None:
        return None
    origin = getattr(original, "forward_origin", None)
    chat = getattr(origin, "chat", None) or getattr(original, "sender_chat", None)
    return chat.id if chat is not None and chat.type == "channel" else None


async def list_text(bot, with_state: bool = False) -> str:
    rows = await check_channels(bot)
    counts = await db_call(gate.stats)
    lines = []
    if with_state:
        on = await db_call(gate.is_on)
        lines += [t("gate.status_title", state=t("gate.status_on") if on else t("gate.status_off")), ""]
    if not rows:
        lines.append(t("gate.list_empty"))
    for row, users_now in zip(rows, counts["channels"]):
        channel = row["channel"]
        lines.append(t("gate.list_line", number=channel.number, title=esc(row["title"]), chat_id=channel.chat_id,
                       admin=t(ADMIN_MARK[row["admin"]])))
        lines.append(t("gate.list_users", users=users_now))
    lines += ["", t("gate.status_rules", period=gate.PERIOD_DAYS), t("gate.list_help")]
    return "\n".join(lines)


async def gate_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.effective_message.reply_text(await list_text(context.bot))


async def gate_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.effective_message.reply_text(await list_text(context.bot, with_state=True))


async def gate_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    message = update.effective_message
    chat_id = forwarded_chat_id(message) or (context.args[0] if context.args else None)
    if chat_id is None:
        await message.reply_text(t("gate.add_how"))
        return
    try:
        chat_id = gate.check_chat_id(chat_id)
    except gate.GateError:
        await message.reply_text(t("gate.add_not_numeric"))
        return
    admin = await bot_is_admin(context.bot, chat_id)
    if admin is not True:
        title = chat_id
        try:
            title = (await context.bot.get_chat(chat_id)).title or chat_id
        except Exception:
            pass
        await message.reply_text(t("gate.add_not_admin", title=esc(title), chat_id=chat_id))
        return
    try:
        channel = await db_call(gate.add_channel, chat_id)
    except gate.GateError as e:
        await message.reply_text(t("gate.add_full", max=gate.MAX_CHANNELS) if str(e) == "full"
                                 else t("gate.add_already"))
        return
    title = await channel_title(context.bot, channel)
    await message.reply_text(t("gate.added", title=esc(title), chat_id=chat_id, number=channel.number))


async def gate_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        number = int(context.args[0])
        gone = await db_call(gate.remove_channel, number)
    except (IndexError, ValueError):   # GateError is a ValueError
        await update.effective_message.reply_text(t("gate.remove_how"))
        return
    title = gone.title or str(gone.chat_id)
    await update.effective_message.reply_text(t("gate.removed", title=esc(title), chat_id=gone.chat_id)
                                              + "\n\n" + await list_text(context.bot))


async def gate_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await db_call(gate.set_on, True)
    text = t("gate.turned_on")
    if not await db_call(gate.channels):
        text += "\n" + t("gate.on_without_channels")
    await update.effective_message.reply_text(text + "\n\n" + await list_text(context.bot))
    await alert_missing_admin(context.bot, await check_channels(context.bot))


async def gate_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await db_call(gate.set_on, False)
        await update.effective_message.reply_text(t("gate.turned_off"))
