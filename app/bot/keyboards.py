"""Button labels, categories, accounts and keyboards. All bot text is sent as HTML and lives in app/strings.py."""
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import filters

from app.strings import t

# ---------------------------------------------------------------------------
# Main menu (the labels are also what the handlers match on)
# ---------------------------------------------------------------------------
BTN_ADD = t("menu.add")
BTN_ADD_INCOME = t("menu.add_income")
BTN_HISTORY = t("menu.history")
BTN_SUMMARY = t("menu.summary")
BTN_BUDGETS = t("menu.budgets")
BTN_ACCOUNTS = t("menu.accounts")
BTN_HELP = t("menu.help")
BTN_SETTINGS = t("menu.settings")
BTN_CANCEL = t("menu.cancel")

MENU_BUTTONS = [BTN_ADD, BTN_ADD_INCOME, BTN_HISTORY, BTN_SUMMARY, BTN_BUDGETS, BTN_ACCOUNTS, BTN_SETTINGS, BTN_HELP]
MENU_OR_CANCEL = filters.Text(MENU_BUTTONS + [BTN_CANCEL])
# Free text typed during a guided flow (amount / note), excluding commands and buttons.
FLOW_TEXT = filters.TEXT & ~filters.COMMAND & ~MENU_OR_CANCEL

CB_FLOW_CANCEL = "flow_cancel"

from app.services.catalog import (  # noqa: E402  (one list for the bot and the Mini App)
    ACCOUNT_LABELS, ACCOUNTS, CATEGORIES, CATEGORY_LABELS, INCOME_CATEGORIES, INCOME_CATEGORY_LABELS,
    account_label, label_for,
)
from app.services.validation import (  # noqa: E402,F401
    MAX_AMOUNT, MAX_NOTE_LENGTH, AmountError, parse_amount,
)

MINUS = "−"  # a real minus sign, not a hyphen


def esc(value) -> str:
    """Escape any dynamic value before it goes into an HTML message."""
    return html.escape(str(value), quote=False)


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------
BTN_OPEN_APP = t("menu.open_app")


def main_menu_keyboard():
    rows = [[BTN_ADD, BTN_ADD_INCOME], [BTN_HISTORY, BTN_SUMMARY], [BTN_BUDGETS, BTN_ACCOUNTS], [BTN_SETTINGS, BTN_HELP]]
    from app.web.server import mini_app_url

    url = mini_app_url()
    if url:  # Telegram only opens Mini Apps over https
        rows[-1].append(KeyboardButton(BTN_OPEN_APP, web_app=WebAppInfo(url=url)))
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


def _grid(buttons, with_cancel: bool):
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    if with_cancel:
        rows.append([InlineKeyboardButton(BTN_CANCEL, callback_data=CB_FLOW_CANCEL)])
    return InlineKeyboardMarkup(rows)


def account_keyboard(prefix: str, options, default: str = None, with_cancel: bool = True, sep: str = "_"):
    """Picker over the user's accounts, `options` = [(key, name)]; the default is marked with ⭐."""
    buttons = [
        InlineKeyboardButton(f"⭐ {label}" if key == default else label, callback_data=f"{prefix}{sep}{key}")
        for key, label in options
    ]
    return _grid(buttons, with_cancel)


def category_keyboard(prefix: str, options):
    """Picker over the user's categories, `options` = [(key, name)]."""
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}_{key}") for key, label in options]
    return _grid(buttons, with_cancel=True)


DATE_CHOICES = [("today", t("date.today")), ("yesterday", t("date.yesterday")), ("other", t("date.other"))]


def note_keyboard(skip_data: str, day_choice: str = "today"):
    """Skip / Cancel, plus the date: Today (default), Yesterday or Other date."""
    dates = [InlineKeyboardButton(("✓ " if key == day_choice else "") + label, callback_data=f"fdate:{key}")
             for key, label in DATE_CHOICES]
    return InlineKeyboardMarkup(
        [dates,
         [InlineKeyboardButton(t("flow.skip"), callback_data=skip_data),
          InlineKeyboardButton(BTN_CANCEL, callback_data=CB_FLOW_CANCEL)]]
    )
