"""Quick entry in the bot: "500 food lunch" logs an entry in one message."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.handlers import budget_warning_text, entry_line
from app.bot.keyboards import category_keyboard, esc, income_category_keyboard, main_menu_keyboard
from app.bot.membership import require_subscription
from app.db import db_call
from app.services import accounts, quick_entry, transactions
from app.services.validation import ValidationError


def undo_keyboard(entry_id: int):
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Undo", callback_data=f"undo:{entry_id}")]])


async def _save(update: Update, context: ContextTypes.DEFAULT_TYPE, parsed: dict, edit_query=None):
    user_id = update.effective_user.id
    account = parsed["account"] or await db_call(accounts.fallback_account, user_id)
    entry, warning = await db_call(
        transactions.add_entry, user_id, parsed["amount_minor"], parsed["type"], parsed["category"], account,
        parsed["note"], parsed.get("day"),
    )
    text = entry_line(entry)
    if warning:
        text += "\n\n" + budget_warning_text(warning)
    if edit_query:
        await edit_query.edit_message_text(text, reply_markup=undo_keyboard(entry["id"]))
    else:
        await update.message.reply_text(text, reply_markup=undo_keyboard(entry["id"]))


@require_subscription
async def quick_entry_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        own_accounts = await db_call(quick_entry.user_accounts, update.effective_user.id)
        parsed = quick_entry.parse(update.message.text, accounts=own_accounts)
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} For example: <code>500 food lunch</code>")
        return
    if parsed is None:
        return
    data = {"amount_minor": parsed.amount_minor, "type": parsed.type, "category": parsed.category,
            "account": parsed.account, "note": parsed.note, "day": parsed.day}
    if parsed.category:
        await _save(update, context, data)
        return
    # No category word: ask for it, with the amount (and any account/note) kept.
    context.user_data["quick"] = data
    keyboard = (income_category_keyboard if parsed.type == "income" else category_keyboard)("qcat")
    sign = "+" if parsed.type == "income" else ""
    await update.message.reply_text(
        f"{sign}{parsed.amount_minor / 100:.2f}: which category?", reply_markup=keyboard
    )


async def quick_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = context.user_data.pop("quick", None)
    if data is None:
        await query.answer("That entry is no longer waiting. Send it again.", show_alert=True)
        return
    await query.answer()
    data["category"] = query.data.split("_", 1)[1]
    try:
        await _save(update, context, data, edit_query=query)
    except ValidationError as e:
        await query.edit_message_text(esc(e))


async def undo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":", 1)[1])
    entry = await db_call(transactions.get_entry, update.effective_user.id, entry_id)
    if not entry or not await db_call(transactions.delete_entry, update.effective_user.id, entry_id):
        await query.answer("Already removed.")
        await query.edit_message_reply_markup(reply_markup=None)
        return
    await query.answer("Undone")
    await query.edit_message_text(f"↩️ Undone: {entry_line(entry)[2:]}")
