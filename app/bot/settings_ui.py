"""The bot's ⚙️ Settings: currency and the weekly recap (Phase 4 adds more here)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import BTN_CANCEL, cancel_keyboard, esc, main_menu_keyboard
from app.bot.membership import require_subscription
from app.db import db_call
from app.services import prefs
from app.services.money import fmt
from app.services.validation import ValidationError

SETTINGS_CURRENCY = 60
CURRENCIES = ["KES", "ETB", "UGX", "TZS", "RWF", "NGN", "GHS", "ZAR", "USD", "EUR", "GBP"]


async def settings_screen(user_id: int):
    p = await db_call(prefs.get_prefs, user_id)
    text = (
        "⚙️ <b>Settings</b>\n\n"
        f"💱 Currency: <b>{esc(p['currency'])}</b> (amounts look like {esc(fmt(150000, p['currency']))})\n"
        f"🔔 Weekly recap: <b>{'on' if p['recap_enabled'] else 'off'}</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Change currency", callback_data="set:currency")],
        [InlineKeyboardButton(f"🔔 Turn weekly recap {'off' if p['recap_enabled'] else 'on'}", callback_data="set:recap")],
    ])
    return text, kb


@require_subscription
async def settings_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await settings_screen(update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=kb)


async def _refresh(query, user_id: int, note: str = ""):
    text, kb = await settings_screen(user_id)
    await query.edit_message_text((note + "\n\n" if note else "") + text, reply_markup=kb)


async def currency_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    current = (await db_call(prefs.get_prefs, update.effective_user.id))["currency"]
    buttons = [InlineKeyboardButton(("• " if c == current else "") + c, callback_data=f"cur:{c}") for c in CURRENCIES]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton("✏️ Another code", callback_data="cur:other"),
                 InlineKeyboardButton("↩️ Back", callback_data="set:back")])
    await query.answer()
    await query.edit_message_text("💱 Pick your currency:", reply_markup=InlineKeyboardMarkup(rows))


async def currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    await db_call(prefs.set_prefs, update.effective_user.id, code)
    await query.answer(f"Currency: {code}")
    await _refresh(query, update.effective_user.id, f"✅ Currency set to {esc(code)}.")


async def toggle_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    current = (await db_call(prefs.get_prefs, update.effective_user.id))["recap_enabled"]
    await db_call(prefs.set_prefs, update.effective_user.id, None, not current)
    await query.answer("Weekly recap " + ("off" if current else "on"))
    await _refresh(query, update.effective_user.id)


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _refresh(update.callback_query, update.effective_user.id)


async def other_currency_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ Type the 3-letter currency code, e.g. <code>ETB</code> or <code>MWK</code>.")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"(Tap {BTN_CANCEL} to stop.)",
                                   reply_markup=cancel_keyboard())
    return SETTINGS_CURRENCY


async def other_currency_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p = await db_call(prefs.set_prefs, update.effective_user.id, update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"{esc(e)} Try again, or tap {BTN_CANCEL}.")
        return SETTINGS_CURRENCY
    await update.message.reply_text(f"✅ Currency set to {esc(p['currency'])}.", reply_markup=main_menu_keyboard())
    text, kb = await settings_screen(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END
