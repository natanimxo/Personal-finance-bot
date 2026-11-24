"""The bot's ⚙️ Settings: currency, timezone, recaps, categories, recurring entries, export."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import BTN_CANCEL, cancel_keyboard, esc, main_menu_keyboard
from app.bot.membership import require_subscription
from app.db import db_call
from app.services import catalog, prefs, timezones
from app.services.money import fmt
from app.services.validation import ValidationError
from app.strings import t

SETTINGS_CURRENCY = 60
CURRENCIES = catalog.COMMON_CURRENCIES


async def settings_screen(user_id: int):
    p = await db_call(prefs.get_prefs, user_id)
    zone = p["timezone"]
    on_off = lambda on: t("common.on") if on else t("common.off")  # noqa: E731
    text = t(
        "settings.screen",
        currency=esc(p["currency"] or t("settings.not_set")), example=esc(fmt(150000, p["currency"])),
        zone=esc(zone or t("settings.not_set")), offset=timezones.offset_label(zone or "UTC"),
        time=timezones.local_time(zone or "UTC"),
        weekly=on_off(p["recap_enabled"]), monthly=on_off(p["monthly_recap_enabled"]),
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("settings.currency_button"), callback_data="set:currency"),
         InlineKeyboardButton(t("settings.timezone_button"), callback_data="tz:settings")],
        [InlineKeyboardButton(t("settings.weekly_button", state=on_off(not p["recap_enabled"])), callback_data="set:recap"),
         InlineKeyboardButton(t("settings.monthly_button", state=on_off(not p["monthly_recap_enabled"])),
                              callback_data="set:mrecap")],
        [InlineKeyboardButton(t("settings.categories_button"), callback_data="cat:list:expense"),
         InlineKeyboardButton(t("settings.recurring_button"), callback_data="set:recurring")],
        [InlineKeyboardButton(t("settings.export_button"), callback_data="set:export")],
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
    rows.append([InlineKeyboardButton(t("settings.another_code"), callback_data="cur:other"),
                 InlineKeyboardButton(t("common.back"), callback_data="set:back")])
    await query.answer()
    await query.edit_message_text(t("settings.pick_currency"), reply_markup=InlineKeyboardMarkup(rows))


async def currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    await db_call(prefs.set_prefs, update.effective_user.id, code)
    await query.answer(t("settings.currency_toast", code=code))
    await _refresh(query, update.effective_user.id, t("settings.currency_set", code=esc(code)))


async def toggle_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """set:recap (weekly) or set:mrecap (monthly)."""
    query = update.callback_query
    monthly = query.data == "set:mrecap"
    field = "monthly_recap_enabled" if monthly else "recap_enabled"
    current = (await db_call(prefs.get_prefs, update.effective_user.id))[field]
    await db_call(prefs.set_prefs, update.effective_user.id, **{field: not current})
    await query.answer(t(f"settings.{'monthly' if monthly else 'weekly'}_{'off' if current else 'on'}"))
    await _refresh(query, update.effective_user.id)


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _refresh(update.callback_query, update.effective_user.id)


async def other_currency_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("settings.type_currency"))
    await context.bot.send_message(chat_id=update.effective_chat.id, text=t("common.tap_cancel", cancel=BTN_CANCEL),
                                   reply_markup=cancel_keyboard())
    return SETTINGS_CURRENCY


async def other_currency_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p = await db_call(prefs.set_prefs, update.effective_user.id, update.message.text)
    except ValidationError as e:
        await update.message.reply_text(t("common.try_again", error=esc(e), cancel=BTN_CANCEL))
        return SETTINGS_CURRENCY
    await update.message.reply_text(t("settings.currency_set", code=esc(p["currency"])), reply_markup=main_menu_keyboard())
    text, kb = await settings_screen(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END


async def send_export(bot, user_id: int):
    """Send the user's CSV into their chat (also used by the Mini App)."""
    import io

    from app.services import export

    data = await db_call(export.csv_bytes, user_id)
    await bot.send_document(
        chat_id=user_id, document=io.BytesIO(data), filename=await db_call(export.filename, user_id),
        caption=t("settings.export_caption"),
    )


async def export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer(t("settings.export_preparing"))
    await send_export(context.bot, update.effective_user.id)


@require_subscription
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_export(context.bot, update.effective_user.id)
