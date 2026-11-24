"""First start: every new user picks their currency and timezone before anything else.

There is no app-wide currency or timezone, so until a user has both, every
update they send (after they've joined the channel) is answered with the next
setup question instead. The same timezone picker is reused from ⚙️ Settings.

    1/2 currency: a button per common currency, or ✏️ Other and a typed code
    2/2 timezone: 📍 share location, a region then a city, or a typed city / UTC+3

The questions are buttons, so the answers come in as callbacks (ob:… for the
currency, tz:… for the timezone). Typed answers and a shared location are only
taken while a question is open (user_data["setup"]). If the bot restarts in the
middle, the next message simply asks the missing question again.
"""
import logging

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update,
)
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.bot.keyboards import BTN_CANCEL, MENU_BUTTONS, esc, main_menu_keyboard
from app.db import db_call
from app.services import accounts, catalog, periods, prefs, timezones
from app.services.money import fmt
from app.services.validation import ValidationError
from app.strings import t

logger = logging.getLogger(__name__)

ADMIN_COMMANDS = ("/recap_now", "/backup_now")


def _grid(buttons, per_row: int):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


# --- questions -----------------------------------------------------------------------
def currency_keyboard():
    buttons = [InlineKeyboardButton(code, callback_data=f"ob:cur:{code}") for code in catalog.COMMON_CURRENCIES]
    rows = _grid(buttons, 4)
    rows.append([InlineKeyboardButton(t("onboard.other_currency"), callback_data="ob:cur:other")])
    return InlineKeyboardMarkup(rows)


async def ask_currency(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    context.user_data["setup"] = {"mode": "onboard", "step": "currency"}
    await context.bot.send_message(chat_id=chat_id, text=t("onboard.currency"), reply_markup=currency_keyboard())


def regions_keyboard():
    buttons = [InlineKeyboardButton(t(f"region.{key}"), callback_data=f"tz:r:{key}") for key in timezones.REGIONS]
    buttons.append(InlineKeyboardButton(t("region.utc"), callback_data="tz:z:UTC"))
    return InlineKeyboardMarkup(_grid(buttons, 2))


def zones_keyboard(region: str):
    buttons = [InlineKeyboardButton(f"{timezones.city(z)} · {timezones.offset_label(z)}", callback_data=f"tz:z:{z}")
               for z in timezones.REGIONS.get(region, [])]
    rows = _grid(buttons, 2)
    rows.append([InlineKeyboardButton(t("onboard.regions"), callback_data="tz:regions")])
    return InlineKeyboardMarkup(rows)


async def ask_timezone(context: ContextTypes.DEFAULT_TYPE, chat_id: int, mode: str = "onboard"):
    """Two messages: the question with a 📍 Share my location keyboard, then the region buttons."""
    context.user_data["setup"] = {"mode": mode, "step": "timezone"}
    rows = [[KeyboardButton(t("onboard.share_location"), request_location=True)]]
    if mode == "settings":
        rows.append([BTN_CANCEL])
    await context.bot.send_message(chat_id=chat_id, text=t("onboard.timezone"),
                                   reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True))
    await context.bot.send_message(chat_id=chat_id, text=t("onboard.pick_region"), reply_markup=regions_keyboard())


async def begin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, p: dict):
    """Ask whichever of the two is still missing."""
    if not p["currency"]:
        await ask_currency(context, chat_id)
    else:
        await ask_timezone(context, chat_id)


# --- answers -------------------------------------------------------------------------------
async def _currency_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user_id = update.effective_user.id
    p = await db_call(prefs.set_prefs, user_id, code)
    done = t("onboard.currency_set", code=esc(p["currency"]), example=esc(fmt(150000, p["currency"])))
    if update.callback_query:
        await update.callback_query.edit_message_text(done)
    else:
        await update.effective_message.reply_text(done)
    if p["timezone"]:
        await _finish(update, context, p)
    else:
        await ask_timezone(context, update.effective_chat.id)


def describe_zone(zone: str) -> str:
    text = t("onboard.timezone_set", zone=esc(timezones.city(zone) if zone.startswith("Etc/") else zone),
             offset=timezones.offset_label(zone), time=timezones.local_time(zone))
    return text + (t("onboard.fixed_offset") if zone.startswith("Etc/") else "")


async def _timezone_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, zone: str):
    user_id = update.effective_user.id
    mode = (context.user_data.pop("setup", None) or {}).get("mode")
    was_onboarded = (await db_call(prefs.get_prefs, user_id))["onboarded"]
    p = await db_call(prefs.set_prefs, user_id, timezone=zone)
    periods.set_zone(p["timezone"], user_id)  # the rest of this update already uses it
    done = describe_zone(p["timezone"])
    query = update.callback_query
    if query:
        await query.edit_message_text(done)
    if mode == "settings" or was_onboarded:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t("common.ok") if query else done,
                                       reply_markup=main_menu_keyboard())
        from app.bot.settings_ui import settings_screen

        text, kb = await settings_screen(user_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)
        return
    if not p["currency"]:  # only if the currency answer was lost in a restart
        if not query:
            await update.effective_message.reply_text(done)
        await ask_currency(context, update.effective_chat.id)
        return
    if not query:
        await update.effective_message.reply_text(done)
    await _finish(update, context, p)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE, p: dict):
    from app.bot.handlers import welcome_text

    context.user_data.pop("setup", None)
    await db_call(accounts.ensure_accounts, update.effective_user.id)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=t("onboard.done"),
                                   reply_markup=main_menu_keyboard())
    await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_text())


async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "ob:cur:other":
        context.user_data["setup"] = {"mode": "onboard", "step": "currency"}
        await query.edit_message_text(t("onboard.type_currency"))
    elif data.startswith("ob:cur:"):
        await _currency_chosen(update, context, data.split(":", 2)[2])
    elif data == "tz:settings":
        await query.edit_message_reply_markup(reply_markup=None)
        await ask_timezone(context, update.effective_chat.id, mode="settings")
    elif data == "tz:regions":
        await query.edit_message_text(t("onboard.pick_region"), reply_markup=regions_keyboard())
    elif data.startswith("tz:r:"):
        await query.edit_message_text(t("onboard.pick_zone"), reply_markup=zones_keyboard(data.split(":", 2)[2]))
    elif data.startswith("tz:z:"):
        zone = data.split(":", 2)[2]
        if timezones.is_valid(zone):
            await _timezone_chosen(update, context, zone)


async def _typed(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    text = update.message.text
    if state["step"] == "currency":
        try:
            await _currency_chosen(update, context, text)
        except ValidationError as e:
            await update.message.reply_text(esc(e))
        return
    zone = timezones.parse(text)
    if zone is None:
        await update.message.reply_text(t("onboard.unknown_timezone"))
        return
    await _timezone_chosen(update, context, zone)


# --- the gate (runs before every other handler) ------------------------------------------------
async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group -1: setup answers go here; a user without a currency and timezone
    gets the next setup question instead of whatever they tapped."""
    user, chat = update.effective_user, update.effective_chat
    if not user or user.is_bot or not chat or chat.type != "private":
        return
    query, message = update.callback_query, update.message
    data = query.data if query else ""
    state = context.user_data.get("setup")

    if data.startswith(("ob:", "tz:")):
        await _callback(update, context)
        raise ApplicationHandlerStop
    if state and message:
        if message.location and state["step"] == "timezone":
            await _timezone_chosen(update, context,
                                   timezones.from_location(message.location.latitude, message.location.longitude))
            raise ApplicationHandlerStop
        if message.text:
            text = message.text.strip()
            moving_on = text in MENU_BUTTONS or text.startswith("/")
            if state["mode"] == "settings":
                if text == BTN_CANCEL:
                    context.user_data.pop("setup", None)
                    await message.reply_text(t("flow.cancelled_inline"), reply_markup=main_menu_keyboard())
                    raise ApplicationHandlerStop
                if moving_on:
                    context.user_data.pop("setup", None)  # they went elsewhere: drop the question
                    return
                await _typed(update, context, state)
                raise ApplicationHandlerStop
            if not moving_on:  # first start: a typed currency code, city or offset
                await _typed(update, context, state)
                raise ApplicationHandlerStop
            # /start, /help or a menu button mid-setup: asked the open question again below

    p = await db_call(prefs.get_prefs, user.id)
    if p["onboarded"]:
        return
    if data == "recheck_sub":
        return  # the channel gate's button; it starts the setup itself once they've joined
    from app.bot.handlers import is_admin
    if is_admin(update) and message and (message.document or (message.text or "").startswith(ADMIN_COMMANDS)):
        return  # an admin can restore a backup or run admin commands before their own setup
    from app.bot.membership import is_subscribed
    if not await is_subscribed(context, user.id):
        return  # the normal handlers show the "join the channel" message
    if query:
        await query.answer()
    if state and not message:
        raise ApplicationHandlerStop  # a stray tap while a question is open
    await begin(context, chat.id, p)
    raise ApplicationHandlerStop
