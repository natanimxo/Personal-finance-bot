"""Admin commands for the channel gate (ADMIN_CHAT_ID only; anyone else gets no reply).

    /gate_add        reply to a post forwarded from the channel (or /gate_add -100...)
    /gate_remove n   take channel n out of the rotation
    /gate_list       the rotation: order, title, id, bot admin, invite right
    /gate_on         check every channel, make the invite links, start checking
    /gate_off        stop checking
    /gate_status     on / off and, per channel, what the gate has done so far
    /gate_stats n    the same numbers for the last n days

Channels are stored by numeric id only. The bot must be an admin of a channel,
with the "Invite users via link" right, for the gate to work there.
"""
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.handlers import is_admin
from app.bot.keyboards import esc
from app.bot.membership import bot_rights, channel_title, check_channels, prepare
from app.db import db_call
from app.services import gate
from app.strings import t

MARK = {True: "gate.yes", False: "gate.no", None: "gate.unknown"}


def forwarded_chat_id(message):
    """The channel a replied-to post was forwarded from, if any."""
    original = message.reply_to_message if message else None
    if original is None:
        return None
    origin = getattr(original, "forward_origin", None)
    chat = getattr(origin, "chat", None) or getattr(original, "sender_chat", None)
    return chat.id if chat is not None and chat.type == "channel" else None


def _rules() -> str:
    return t("gate.rules", free=gate.FREE_DAYS, period=gate.PERIOD_DAYS)


def _list_lines(rows):
    if not rows:
        return [t("gate.list_empty")]
    return [t("gate.list_line", number=r["channel"].number, title=esc(r["title"]), chat_id=r["channel"].chat_id,
              admin=t(MARK[r["admin"]]), invite=t(MARK[r["can_invite"]])) for r in rows]


async def list_text(bot) -> str:
    on = await db_call(gate.is_on)
    lines = [t("gate.status_title", state=t("gate.status_on") if on else t("gate.status_off")), ""]
    lines += _list_lines(await check_channels(bot))
    lines += ["", _rules(), t("gate.list_help")]
    return "\n".join(lines)


async def numbers_text(bot, days: int = None) -> str:
    on = await db_call(gate.is_on)
    data = await db_call(gate.stats, days)
    title = t("gate.stats_title", days=days) if days else \
        t("gate.status_title", state=t("gate.status_on") if on else t("gate.status_off"))
    lines = [title, ""]
    if not data["channels"]:
        lines.append(t("gate.list_empty"))
    for row in data["channels"]:
        channel = row["channel"]
        lines.append(t("gate.count_title", number=channel.number, title=esc(await channel_title(bot, channel))))
        lines.append(t("gate.count_line", **{k: row[k] for k in (
            "required", "shown", "joined_via_bot", "already_member", "left", "rejoined", "subscribed")}))
    lines += ["", t("gate.free_users", users=data["free"], free=gate.FREE_DAYS), _rules()]
    return "\n".join(lines)


async def gate_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.effective_message.reply_text(await list_text(context.bot))


async def gate_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.effective_message.reply_text(await numbers_text(context.bot))


async def gate_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        days = int(context.args[0])
        if days < 1:
            raise ValueError
    except (IndexError, ValueError):
        await update.effective_message.reply_text(t("gate.stats_how"))
        return
    await update.effective_message.reply_text(await numbers_text(context.bot, days))


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
    admin, _ = await bot_rights(context.bot, chat_id)
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
    if await db_call(gate.is_on):
        await prepare(context.bot)   # its invite link now, as the gate is already on
    title = await channel_title(context.bot, channel)
    await message.reply_text(t("gate.added", title=esc(title), chat_id=chat_id, number=channel.number))


async def gate_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        gone = await db_call(gate.remove_channel, int(context.args[0]))
    except (IndexError, ValueError):   # GateError is a ValueError
        await update.effective_message.reply_text(t("gate.remove_how"))
        return
    title = gone.title or str(gone.chat_id)
    await update.effective_message.reply_text(t("gate.removed", title=esc(title), chat_id=gone.chat_id)
                                              + "\n\n" + await list_text(context.bot))


async def gate_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turn on: check every channel (admin, invite right), make the invite links,
    and report anything that fails (also as an alert)."""
    if not is_admin(update):
        return
    await db_call(gate.set_on, True)
    rows = await prepare(context.bot)
    text = t("gate.turned_on")
    if not rows:
        text += "\n" + t("gate.on_without_channels")
    lines = [t("gate.list_line", number=r["channel"].number, title=esc(r["title"]), chat_id=r["channel"].chat_id,
               admin=t(MARK[r["admin"]]), invite=t(MARK[bool(r.get("link"))])) for r in rows]
    await update.effective_message.reply_text("\n".join([text, ""] + lines + ["", _rules()]))


async def gate_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await db_call(gate.set_on, False)
        await update.effective_message.reply_text(t("gate.turned_off"))
