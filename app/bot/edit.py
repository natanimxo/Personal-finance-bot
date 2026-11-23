"""Editing a saved entry from the bot: amount, category, account or note (date in Phase 4.3).

History's ✏️ Edit opens the entry with one button per field. Category and account
are picked with buttons; amount and note are typed, which is a small conversation
inside the main flow handler (EDIT_TEXT), so Cancel and the menu buttons work as
everywhere else.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.handlers import budget_warning_text, entry_line
from app.bot.keyboards import (
    ACCOUNTS, BTN_CANCEL, CATEGORIES, INCOME_CATEGORIES, MAX_NOTE_LENGTH, cancel_keyboard, esc,
    main_menu_keyboard, parse_amount,
)
from app.db import db_call
from app.services import transactions
from app.services.validation import ValidationError, to_minor

EDIT_TEXT = 30


def edit_menu(entry_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Amount", callback_data=f"edf:amount:{entry_id}"),
         InlineKeyboardButton("🏷️ Category", callback_data=f"edcat:{entry_id}")],
        [InlineKeyboardButton("🏦 Account", callback_data=f"edacc:{entry_id}"),
         InlineKeyboardButton("📝 Note", callback_data=f"edf:note:{entry_id}")],
        [InlineKeyboardButton("✅ Done", callback_data=f"eddone:{entry_id}")],
    ])


def choice_keyboard(buttons, entry_id: int) -> InlineKeyboardMarkup:
    """Two buttons a row, then ↩️ Back to the field menu."""
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=f"edit:{entry_id}")])
    return InlineKeyboardMarkup(rows)


def editing_text(entry, extra: str = "") -> str:
    return "✏️ <b>Editing</b>\n" + entry_line(entry) + (f"\n\n{extra}" if extra else "") + "\n\nWhat do you want to change?"


async def _load(update: Update, entry_id: int):
    entry = await db_call(transactions.get_entry, update.effective_user.id, entry_id)
    if entry is None:
        await update.callback_query.answer("That entry was deleted.", show_alert=True)
    return entry


async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":")[-1])
    entry = await _load(update, entry_id)
    if entry:
        await query.answer()
        await query.edit_message_text(editing_text(entry), reply_markup=edit_menu(entry_id))


async def edit_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry = await _load(update, int(query.data.split(":")[1]))
    if entry:
        await query.answer("Saved")
        await query.edit_message_text(entry_line(entry).replace("Logged", "Saved", 1))


async def edit_category_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":")[1])
    entry = await _load(update, entry_id)
    if not entry:
        return
    await query.answer()
    options = INCOME_CATEGORIES if entry["type"] == "income" else CATEGORIES
    kb = choice_keyboard([InlineKeyboardButton(("• " if k == entry["category"] else "") + label,
                                               callback_data=f"edsetcat:{entry_id}:{k}") for k, label in options], entry_id)
    await query.edit_message_reply_markup(reply_markup=kb)


async def edit_account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":")[1])
    entry = await _load(update, entry_id)
    if not entry:
        return
    await query.answer()
    kb = choice_keyboard([InlineKeyboardButton(("• " if k == entry["account"] else "") + label,
                                               callback_data=f"edsetacc:{entry_id}:{k}") for k, label in ACCOUNTS], entry_id)
    await query.edit_message_reply_markup(reply_markup=kb)


async def _apply(update: Update, entry_id: int, **changes):
    """Save the change and return (entry, text) for the editing message."""
    entry, warning = await db_call(transactions.update_entry, update.effective_user.id, entry_id, **changes)
    if entry is None:
        return None, None
    return entry, editing_text(entry, budget_warning_text(warning) if warning else "✅ Saved.")


async def edit_set_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kind, entry_id, key = query.data.split(":", 2)
    field = "category" if kind == "edsetcat" else "account"
    try:
        entry, text = await _apply(update, int(entry_id), **{field: key})
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    if entry is None:
        await query.answer("That entry was deleted.", show_alert=True)
        return
    await query.answer("Saved")
    await query.edit_message_text(text, reply_markup=edit_menu(entry["id"]))


# --- typed fields (amount, note): a conversation step ---------------------------------
async def edit_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, field, entry_id = query.data.split(":")
    entry = await _load(update, int(entry_id))
    if not entry:
        return ConversationHandler.END
    await query.answer()
    context.user_data["editing"] = {"id": entry["id"], "field": field}
    prompt = (f"Type the new amount (now {entry['amount']:.2f})." if field == "amount"
              else f"Type the new note (up to {MAX_NOTE_LENGTH} characters), or send <code>-</code> to clear it.")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=prompt, reply_markup=cancel_keyboard())
    return EDIT_TEXT


async def edit_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    editing = context.user_data.get("editing")
    if not editing:
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        if editing["field"] == "amount":
            changes = {"amount_minor": to_minor(parse_amount(text))}
        else:
            changes = {"note": "" if text == "-" else text}
        entry, message = await _apply(update, editing["id"], **changes)
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} Try again, or tap {BTN_CANCEL}.")
        return EDIT_TEXT
    context.user_data.pop("editing", None)
    if entry is None:
        await update.message.reply_text("That entry was deleted.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("👍", reply_markup=main_menu_keyboard())
    await update.message.reply_text(message, reply_markup=edit_menu(entry["id"]))
    return ConversationHandler.END
