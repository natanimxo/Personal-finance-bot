"""Managing accounts from the bot's 🏦 Accounts screen: add, rename, archive, restore.

Naming (add / rename) is typed, so it is a step in the main flow handler
(ACCOUNT_NAME); archive and restore are buttons.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.handlers import accounts_screen, entry_line
from app.bot.quick import undo_keyboard
from app.bot.keyboards import BTN_CANCEL, CB_FLOW_CANCEL, cancel_keyboard, esc, main_menu_keyboard, parse_amount
from app.db import db_call
from app.services import accounts, transactions
from app.services.validation import ValidationError, to_minor

ACCOUNT_NAME = 50
TRANSFER_FROM, TRANSFER_TO, TRANSFER_AMOUNT = range(51, 54)


def _pick(options, action: str, back_label: str = "↩️ Back"):
    rows = [[InlineKeyboardButton(name, callback_data=f"acc:{action}:{key}")] for key, name in options]
    rows.append([InlineKeyboardButton(back_label, callback_data="acc:back")])
    return InlineKeyboardMarkup(rows)


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text, kb = await accounts_screen(update.effective_user.id)
    await query.edit_message_text(text, reply_markup=kb)


async def choose_for(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """acc:ren / acc:arch / acc:restore -> list the accounts to act on."""
    query = update.callback_query
    action = query.data.split(":")[1]
    rows = await db_call(accounts.list_accounts, update.effective_user.id, True)
    if action == "restore":
        options = [(a["key"], a["name"]) for a in rows if a["archived"]]
        title, act = "♻️ Which account do you want back?", "unarch"
    else:
        options = [(a["key"], a["name"]) for a in rows if not a["archived"]]
        title, act = ("✏️ Which account do you want to rename?", "ren") if action == "ren" else \
                     ("🗄️ Which account do you want to archive? Its history and balance stay.", "archive")
    await query.answer()
    await query.edit_message_text(title, reply_markup=_pick(options, act))


async def archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, act, key = query.data.split(":", 2)
    try:
        await db_call(accounts.set_archived, update.effective_user.id, key, act == "archive")
    except ValidationError as e:
        await query.answer(str(e), show_alert=True)
        return
    names = await db_call(accounts.names, update.effective_user.id)
    await query.answer("Archived" if act == "archive" else "Restored")
    text, kb = await accounts_screen(update.effective_user.id)
    done = f"🗄️ Archived {esc(names[key])}." if act == "archive" else f"♻️ {esc(names[key])} is back."
    await query.edit_message_text(f"{done}\n\n{text}", reply_markup=kb)


# --- typed names -----------------------------------------------------------------
async def name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """acc:add, or acc:ren:<key> from the rename list."""
    query = update.callback_query
    parts = query.data.split(":", 2)
    await query.answer()
    if parts[1] == "add":
        context.user_data["account_naming"] = {"key": None}
        prompt = "➕ What's the new account called? (e.g. <i>Savings</i> or <i>Telebirr</i>)"
    else:
        names = await db_call(accounts.names, update.effective_user.id)
        context.user_data["account_naming"] = {"key": parts[2]}
        prompt = f"✏️ New name for {esc(names.get(parts[2], parts[2]))}? Its history and balance stay."
    await query.edit_message_text(prompt)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"(Tap {BTN_CANCEL} to stop.)",
                                   reply_markup=cancel_keyboard())
    return ACCOUNT_NAME


async def name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    naming = context.user_data.get("account_naming")
    if naming is None:
        return ConversationHandler.END
    name = update.message.text
    try:
        if naming["key"] is None:
            account = await db_call(accounts.add_account, update.effective_user.id, name)
            done = f"✅ Added {esc(account['name'])}."
        else:
            account = await db_call(accounts.rename_account, update.effective_user.id, naming["key"], name)
            done = f"✅ Renamed to {esc(account['name'])}."
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} Try another name, or tap {BTN_CANCEL}.")
        return ACCOUNT_NAME
    context.user_data.pop("account_naming", None)
    await update.message.reply_text(done, reply_markup=main_menu_keyboard())
    text, kb = await accounts_screen(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END


# --- transfers: From -> To -> amount ----------------------------------------------------
def _account_buttons(options, prefix: str):
    rows = [[InlineKeyboardButton(name, callback_data=f"{prefix}:{key}")] for key, name in options]
    rows.append([InlineKeyboardButton(BTN_CANCEL, callback_data=CB_FLOW_CANCEL)])
    return InlineKeyboardMarkup(rows)


async def transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    options = await db_call(accounts.choices, update.effective_user.id)
    await query.answer()
    if len(options) < 2:
        await query.edit_message_text("You need two accounts to move money between. Add one first.")
        return ConversationHandler.END
    context.user_data["transfer"] = {}
    await query.edit_message_text("🔁 <b>Transfer</b>\nMove money <b>from</b> which account?",
                                  reply_markup=_account_buttons(options, "trf"))
    return TRANSFER_FROM


async def transfer_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = query.data.split(":", 1)[1]
    context.user_data.setdefault("transfer", {})["from"] = key
    options = await db_call(accounts.choices, update.effective_user.id)
    names = dict(options)
    await query.answer()
    await query.edit_message_text(f"🔁 From <b>{esc(names.get(key, key))}</b> <b>to</b> which account?",
                                  reply_markup=_account_buttons([o for o in options if o[0] != key], "trt"))
    return TRANSFER_TO


async def transfer_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    transfer = context.user_data.setdefault("transfer", {})
    transfer["to"] = query.data.split(":", 1)[1]
    names = await db_call(accounts.names, update.effective_user.id)
    await query.answer()
    await query.edit_message_text(
        f"🔁 {esc(names.get(transfer['from'], ''))} → {esc(names.get(transfer['to'], ''))}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="How much? (e.g. 500)",
                                   reply_markup=cancel_keyboard())
    return TRANSFER_AMOUNT


async def transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transfer = context.user_data.get("transfer") or {}
    try:
        amount = parse_amount(update.message.text)
        entry = await db_call(transactions.add_transfer, update.effective_user.id, to_minor(amount),
                              transfer.get("from"), transfer.get("to"))
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} Try again, or tap {BTN_CANCEL}.")
        return TRANSFER_AMOUNT
    context.user_data.pop("transfer", None)
    await update.message.reply_text("👍", reply_markup=main_menu_keyboard())
    await update.message.reply_text(entry_line(entry), reply_markup=undo_keyboard(entry["id"]))
    return ConversationHandler.END
