"""Button labels, categories, accounts and keyboards. All bot text is sent as HTML."""
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import filters

# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------
BTN_ADD = "➕ Add Expense"
BTN_ADD_INCOME = "💵 Add Income"
BTN_HISTORY = "📋 History"
BTN_SUMMARY = "📊 Summary"
BTN_BUDGETS = "💰 Budgets"
BTN_ACCOUNTS = "🏦 Accounts"
BTN_HELP = "❓ Help"
BTN_CANCEL = "❌ Cancel"

MENU_BUTTONS = [BTN_ADD, BTN_ADD_INCOME, BTN_HISTORY, BTN_SUMMARY, BTN_BUDGETS, BTN_ACCOUNTS, BTN_HELP]
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
BTN_OPEN_APP = "📱 Open app"


def main_menu_keyboard():
    rows = [[BTN_ADD, BTN_ADD_INCOME], [BTN_HISTORY, BTN_SUMMARY], [BTN_BUDGETS, BTN_ACCOUNTS], [BTN_HELP]]
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


def account_keyboard(prefix: str, default: str = None, with_cancel: bool = True, sep: str = "_"):
    """Account picker; the default account (if any) is marked with ⭐."""
    buttons = [
        InlineKeyboardButton(f"⭐ {label}" if key == default else label, callback_data=f"{prefix}{sep}{key}")
        for key, label in ACCOUNTS
    ]
    return _grid(buttons, with_cancel)


def category_keyboard(prefix: str):
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}_{key}") for key, label in CATEGORIES]
    return _grid(buttons, with_cancel=True)


def income_category_keyboard(prefix: str):
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}_{key}") for key, label in INCOME_CATEGORIES]
    return _grid(buttons, with_cancel=True)


def note_keyboard(skip_data: str):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏭️ Skip", callback_data=skip_data),
          InlineKeyboardButton(BTN_CANCEL, callback_data=CB_FLOW_CANCEL)]]
    )
