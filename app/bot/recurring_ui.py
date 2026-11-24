"""Recurring entries in the bot: make one from an entry, list and delete them,
and the hourly job that creates what is due (from 06:00 in each user's own
timezone) and tells the user (with Undo)."""
import logging
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from app.bot.handlers import entry_line
from app.bot.keyboards import esc
from app.bot.quick import undo_keyboard
from app.db import db_call
from app.services import periods, prefs, recurring, transactions
from app.services.money import fmt
from app.services.validation import ValidationError
from app.strings import t

logger = logging.getLogger(__name__)
EVERY = {"weekly": t("recurring.every_weekly"), "monthly": t("recurring.every_monthly")}


async def repeat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":")[1])
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("recurring.weekly"), callback_data=f"repset:{entry_id}:weekly"),
         InlineKeyboardButton(t("recurring.monthly"), callback_data=f"repset:{entry_id}:monthly")],
        [InlineKeyboardButton(t("common.back"), callback_data=f"edit:{entry_id}")],
    ]))


async def repeat_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, frequency = query.data.split(":")
    try:
        rule = await db_call(recurring.create_from_entry, update.effective_user.id, int(entry_id), frequency)
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    await query.answer(t("recurring.repeating_toast"))
    next_day = date.fromisoformat(rule["next_date"])
    await query.edit_message_text(t("recurring.now_repeats", every=EVERY[frequency], day=next_day))


def _rule_line(rule, currency: str) -> str:
    signed = rule["amount_minor"] if rule["type"] == "income" else -rule["amount_minor"]
    note = t("history.note", note=esc(rule["note"])) if rule["note"] else ""
    return t("recurring.rule_line", amount=fmt(signed, currency, sign=True), label=esc(rule["category_label"]),
             note=note, every=EVERY[rule["frequency"]], day=date.fromisoformat(rule["next_date"]))


async def recurring_screen(user_id: int):
    rules = await db_call(recurring.list_rules, user_id)
    currency = (await db_call(prefs.get_prefs, user_id))["currency"]
    if not rules:
        return t("recurring.empty"), InlineKeyboardMarkup([[InlineKeyboardButton(t("common.back"), callback_data="set:back")]])
    lines = [t("recurring.title"), ""] + [f"{i}. {_rule_line(r, currency)}" for i, r in enumerate(rules, 1)]
    buttons = [[InlineKeyboardButton(t("recurring.stop", n=i), callback_data=f"repdel:{r['id']}")]
               for i, r in enumerate(rules, 1)]
    buttons.append([InlineKeyboardButton(t("common.back"), callback_data="set:back")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def recurring_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text, kb = await recurring_screen(update.effective_user.id)
    await query.edit_message_text(text, reply_markup=kb)


async def recurring_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rule_id = int(query.data.split(":")[1])
    ok = await db_call(recurring.delete_rule, update.effective_user.id, rule_id)
    await query.answer(t("recurring.stopped") if ok else t("recurring.already_stopped"))
    text, kb = await recurring_screen(update.effective_user.id)
    await query.edit_message_text(text, reply_markup=kb)


async def recurring_job(context: ContextTypes.DEFAULT_TYPE):
    """Hourly: create the entries now due (06:00 or later on their date, the user's
    time), then tell each user (with Undo)."""
    created = await db_call(recurring.process_due)
    for rule, entry_id in created:
        user_id = rule["user_id"]
        entry = await db_call(transactions.get_entry, user_id, entry_id)
        if entry is None:
            continue
        with periods.use_zone(await db_call(periods.user_zone_name, user_id), user_id):
            text = t("recurring.logged", line=entry_line(entry))
        try:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=undo_keyboard(entry_id))
        except Forbidden:
            pass  # they blocked the bot; the recap marks them inactive
        except Exception as e:
            logger.warning(f"Couldn't tell {rule['user_id']} about recurring entry {entry_id}: {e}")
