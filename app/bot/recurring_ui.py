"""Recurring entries in the bot: make one from an entry, list and delete them,
and the daily job that creates what is due and tells the user (with Undo)."""
import logging
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from app.bot.handlers import entry_line
from app.bot.keyboards import esc
from app.bot.quick import undo_keyboard
from app.db import db_call
from app.services import prefs, recurring, transactions
from app.services.money import fmt
from app.services.validation import ValidationError

logger = logging.getLogger(__name__)
EVERY = {"weekly": "every week", "monthly": "every month"}


async def repeat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":")[1])
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Weekly", callback_data=f"repset:{entry_id}:weekly"),
         InlineKeyboardButton("Monthly", callback_data=f"repset:{entry_id}:monthly")],
        [InlineKeyboardButton("↩️ Back", callback_data=f"edit:{entry_id}")],
    ]))


async def repeat_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, frequency = query.data.split(":")
    try:
        rule = await db_call(recurring.create_from_entry, update.effective_user.id, int(entry_id), frequency)
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    await query.answer("Repeating")
    next_day = date.fromisoformat(rule["next_date"])
    await query.edit_message_text(
        f"🔁 This now repeats {EVERY[frequency]}. The next one is logged on {next_day:%a %d %b %Y}.\n"
        "Manage repeats in ⚙️ Settings → 🔁 Recurring.")


def _rule_line(rule, currency: str) -> str:
    signed = rule["amount_minor"] if rule["type"] == "income" else -rule["amount_minor"]
    note = f" — {esc(rule['note'])}" if rule["note"] else ""
    return (f"{fmt(signed, currency, sign=True)} {esc(rule['category_label'])}{note}, {EVERY[rule['frequency']]} "
            f"(next {date.fromisoformat(rule['next_date']):%d %b})")


async def recurring_screen(user_id: int):
    rules = await db_call(recurring.list_rules, user_id)
    currency = (await db_call(prefs.get_prefs, user_id))["currency"]
    if not rules:
        text = ("🔁 <b>Recurring entries</b>\n\nNone yet. To repeat an entry (rent, salary, a subscription), "
                "open it from 📋 History → ✏️ Edit → 🔁 Repeat.")
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="set:back")]])
    lines = ["🔁 <b>Recurring entries</b>", ""] + [f"{i}. {_rule_line(r, currency)}" for i, r in enumerate(rules, 1)]
    buttons = [[InlineKeyboardButton(f"🗑️ Stop #{i}", callback_data=f"repdel:{r['id']}")] for i, r in enumerate(rules, 1)]
    buttons.append([InlineKeyboardButton("↩️ Back", callback_data="set:back")])
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
    await query.answer("Stopped. Past entries stay." if ok else "Already stopped.")
    text, kb = await recurring_screen(update.effective_user.id)
    await query.edit_message_text(text, reply_markup=kb)


async def recurring_job(context: ContextTypes.DEFAULT_TYPE):
    """06:00 daily: create due entries, then tell each user (with Undo)."""
    created = await db_call(recurring.process_due)
    for rule, entry_id in created:
        entry = await db_call(transactions.get_entry, rule["user_id"], entry_id)
        if entry is None:
            continue
        try:
            await context.bot.send_message(chat_id=rule["user_id"], text="🔁 <b>Recurring</b>\n" + entry_line(entry),
                                           reply_markup=undo_keyboard(entry_id))
        except Forbidden:
            pass  # they blocked the bot; the recap marks them inactive
        except Exception as e:
            logger.warning(f"Couldn't tell {rule['user_id']} about recurring entry {entry_id}: {e}")
