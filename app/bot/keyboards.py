"""Button labels, categories, accounts and keyboards. All bot text is sent as HTML."""
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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

ACCOUNTS = [
    ("cash", "💵 Cash"),
    ("bank", "🏦 Bank"),
    ("card", "💳 Card"),
    ("mobile_money", "📱 Mobile Wallets"),
]
ACCOUNT_LABELS = dict(ACCOUNTS)

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

MINUS = "−"  # a real minus sign, not a hyphen


def esc(value) -> str:
    """Escape any dynamic value before it goes into an HTML message."""
    return html.escape(str(value), quote=False)


def label_for(category_key: str, type_: str) -> str:
    table = INCOME_CATEGORY_LABELS if type_ == "income" else CATEGORY_LABELS
    return table.get(category_key, f"📦 {category_key}")


def account_label(account_key: str) -> str:
    return ACCOUNT_LABELS.get(account_key, account_key)


def parse_amount(text: str) -> float:
    """Accepts 12.50, 1,200 or 1 200. Raises ValueError for anything else or <= 0."""
    amount = float(text.strip().replace(",", "").replace(" ", ""))
    if amount <= 0 or amount != amount or amount == float("inf"):
        raise ValueError
    return amount


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_ADD, BTN_ADD_INCOME], [BTN_HISTORY, BTN_SUMMARY], [BTN_BUDGETS, BTN_ACCOUNTS], [BTN_HELP]],
        resize_keyboard=True,
    )


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
