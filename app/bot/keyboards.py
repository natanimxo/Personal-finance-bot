from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, ContextTypes, filters

# ---------------------------------------------------------------------------
# Menu layout
# ---------------------------------------------------------------------------
BTN_ADD = "➕ Add Expense"
BTN_ADD_INCOME = "💵 Add Income"
BTN_HISTORY = "📋 History"
BTN_SUMMARY = "📊 Summary"
BTN_BUDGETS = "💰 Budgets"
BTN_ACCOUNTS = "🏦 Accounts"
BTN_HELP = "❓ Help"
BTN_CANCEL = "❌ Cancel"

ACCOUNTS = [
    ("cash", "💵 Cash"),
    ("bank", "🏦 Bank"),
    ("card", "💳 Card"),
    ("mobile_money", "📱 Mobile Wallets"),
]
ACCOUNT_LABELS = dict(ACCOUNTS)


def account_keyboard(prefix: str, default: str = None):
    """Account picker. The default account (if given) comes first, marked with ⭐."""
    ordered = sorted(ACCOUNTS, key=lambda a: a[0] != default) if default else ACCOUNTS
    buttons = [
        InlineKeyboardButton(f"⭐ {label}" if key == default else label, callback_data=f"{prefix}_{key}")
        for key, label in ordered
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)

CATEGORIES = [
    ("food", "🍔 Food"),
    ("transport", "🚗 Transport"),
    ("bills", "🧾 Bills"),
    ("shopping", "🛍️ Shopping"),
    ("fun", "🎉 Fun"),
    ("other", "📦 Other"),
]
CATEGORY_LABELS = dict(CATEGORIES)

INCOME_CATEGORIES = [
    ("salary", "💼 Salary"),
    ("freelance", "🧑‍💻 Freelance"),
    ("business", "🏢 Business"),
    ("gift", "🎁 Gift"),
    ("other", "📦 Other"),
]
INCOME_CATEGORY_LABELS = dict(INCOME_CATEGORIES)


def label_for(category_key: str, type_: str) -> str:
    table = INCOME_CATEGORY_LABELS if type_ == "income" else CATEGORY_LABELS
    return table.get(category_key, f"📦 {category_key}")


ASK_AMOUNT, ASK_CATEGORY, ASK_ACCOUNT, ASK_NOTE = range(4)
ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_ACCOUNT, ASK_INCOME_NOTE = range(10, 14)
BUDGET_CATEGORY, BUDGET_AMOUNT = range(20, 22)


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_ADD, BTN_ADD_INCOME], [BTN_HISTORY, BTN_SUMMARY], [BTN_BUDGETS, BTN_ACCOUNTS], [BTN_HELP]],
        resize_keyboard=True,
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


MENU_BUTTONS = [BTN_ADD, BTN_ADD_INCOME, BTN_HISTORY, BTN_SUMMARY, BTN_BUDGETS, BTN_ACCOUNTS, BTN_HELP]
MENU_OR_CANCEL = filters.Text(MENU_BUTTONS + [BTN_CANCEL])
# Free text typed during a guided flow (amount / note), excluding commands and buttons.
FLOW_TEXT = filters.TEXT & ~filters.COMMAND & ~MENU_OR_CANCEL


def parse_amount(text: str) -> float:
    """Accepts 12.50, 1,200 or 1 200. Raises ValueError for anything else or <= 0."""
    amount = float(text.strip().replace(",", "").replace(" ", ""))
    if amount <= 0 or amount != amount or amount == float("inf"):
        raise ValueError
    return amount


def month_start() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def category_keyboard(prefix: str):
    buttons = [
        InlineKeyboardButton(label, callback_data=f"{prefix}_{key}")
        for key, label in CATEGORIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def income_category_keyboard(prefix: str):
    buttons = [
        InlineKeyboardButton(label, callback_data=f"{prefix}_{key}")
        for key, label in INCOME_CATEGORIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)
