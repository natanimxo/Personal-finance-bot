"""Bot screens and the guided add-entry / budget flows.

Every message goes out as HTML (the Application's default parse mode), and every
dynamic value (notes, labels, links) is passed through esc() first.
"""
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app import config
from app.bot.keyboards import (
    BTN_ACCOUNTS, BTN_ADD, BTN_ADD_INCOME, BTN_BUDGETS, BTN_CANCEL, BTN_HELP, BTN_HISTORY, BTN_SUMMARY,
    ACCOUNTS, CATEGORY_LABELS, INCOME_CATEGORY_LABELS, MINUS,
    account_keyboard, account_label, cancel_keyboard, category_keyboard, esc, income_category_keyboard,
    MAX_NOTE_LENGTH, label_for, main_menu_keyboard, note_keyboard, parse_amount,
)
from app.bot.membership import is_subscribed, require_subscription, send_gate, touch_user
from app.db import db_call
from app.services import accounts, budgets, periods, summaries, transactions, users
from app.services.backup import run_backup
from app.services.validation import to_minor
from app.services.recap import recap_text

logger = logging.getLogger(__name__)

ASK_AMOUNT, ASK_CATEGORY, ASK_ACCOUNT, ASK_NOTE = range(4)
ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_ACCOUNT, ASK_INCOME_NOTE = range(10, 14)
BUDGET_CATEGORY, BUDGET_AMOUNT = range(20, 22)

PENDING_KEYS = ("pending_amount", "pending_category", "pending_account", "used_default", "pending_budget_category",
                "editing")


def clear_pending(context: ContextTypes.DEFAULT_TYPE):
    for key in PENDING_KEYS:
        context.user_data.pop(key, None)


# ---------------------------------------------------------------------------
# Start / Help
# ---------------------------------------------------------------------------
@require_subscription
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 <b>Welcome!</b>\n\n"
        "I'm your expense tracker. Everything works through the buttons below "
        "— no typing commands needed.\n\n"
        f"{BTN_ADD} — log a spend in 3 taps\n"
        f"{BTN_ADD_INCOME} — log income in 3 taps\n"
        f"{BTN_HISTORY} — see your recent transactions\n"
        f"{BTN_SUMMARY} — income, expenses, net and savings rate\n"
        f"{BTN_BUDGETS} — set spending limits &amp; get warned\n"
        f"{BTN_ACCOUNTS} — balances across Cash/Bank/Card/Mobile Wallets\n\n"
        "I'll also message you every Monday morning with last week's recap.",
        reply_markup=main_menu_keyboard(),
    )


@require_subscription
async def help_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "<b>How this works</b>\n\n"
        f"1️⃣ Tap {BTN_ADD} or {BTN_ADD_INCOME}\n"
        "2️⃣ Type the amount\n"
        "3️⃣ Tap a category button\n"
        "4️⃣ Tap an account. If you set a ⭐ default account, this step is skipped\n"
        "5️⃣ Add a note, or skip it\n\n"
        f"Changed your mind? Tap {BTN_CANCEL} at any step, or any menu button.\n\n"
        "Use the other buttons any time to check your history, totals, or budgets.",
        reply_markup=main_menu_keyboard(),
    )


# ---------------------------------------------------------------------------
# Add expense / income — one guided flow, parameterised by type
# ---------------------------------------------------------------------------
FLOW = {
    "expense": {
        "ask": "💵 How much did you spend? (just type the number, e.g. 12.50)",
        "example": "12.50",
        "cat_prefix": "addcat", "acc_prefix": "addacc", "skip": "skip_note",
        "states": (ASK_AMOUNT, ASK_CATEGORY, ASK_ACCOUNT, ASK_NOTE),
        "labels": CATEGORY_LABELS, "keyboard": category_keyboard,
    },
    "income": {
        "ask": "💵 How much did you receive? (just type the number, e.g. 500)",
        "example": "500",
        "cat_prefix": "inccat", "acc_prefix": "incacc", "skip": "skip_income_note",
        "states": (ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_ACCOUNT, ASK_INCOME_NOTE),
        "labels": INCOME_CATEGORY_LABELS, "keyboard": income_category_keyboard,
    },
}


async def _flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    user_id = update.effective_user.id
    if not await is_subscribed(context, user_id):
        await send_gate(update)
        return ConversationHandler.END
    await touch_user(user_id)
    clear_pending(context)
    await update.message.reply_text(FLOW[type_]["ask"], reply_markup=cancel_keyboard())
    return FLOW[type_]["states"][0]


async def _flow_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    cfg = FLOW[type_]
    try:
        amount = parse_amount(update.message.text)
    except ValueError as e:
        await update.message.reply_text(f"{esc(e)} Try again, e.g. {cfg['example']}")
        return cfg["states"][0]
    context.user_data["pending_amount"] = amount
    await update.message.reply_text("Pick a category:", reply_markup=cfg["keyboard"](cfg["cat_prefix"]))
    return cfg["states"][1]


async def _ask_note(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Want to add a quick note? Type it, or tap Skip.",
        reply_markup=note_keyboard(FLOW[type_]["skip"]),
    )
    return FLOW[type_]["states"][3]


async def _flow_category(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    cfg = FLOW[type_]
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_category"] = category_key
    await query.edit_message_text(f"Category: {esc(cfg['labels'][category_key])}")

    default = await db_call(accounts.get_default_account, update.effective_user.id)
    if default:
        # A default account is set: skip the account step. The confirmation
        # offers "Change account" instead.
        context.user_data["pending_account"] = default
        context.user_data["used_default"] = True
        return await _ask_note(update, context, type_)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Which account?",
        reply_markup=account_keyboard(cfg["acc_prefix"]),
    )
    return cfg["states"][2]


async def _flow_account(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    context.user_data["pending_account"] = account_key
    await query.edit_message_text(f"Account: {esc(account_label(account_key))}")
    return await _ask_note(update, context, type_)


def entry_line(entry) -> str:
    type_ = entry["type"]
    sign = "+" if type_ == "income" else MINUS
    icon = "💵" if type_ == "income" else "✅"
    text = (
        f"{icon} Logged {sign}{entry['amount']:.2f} — {esc(label_for(entry['category'], type_))} "
        f"({esc(account_label(entry['account']))})"
    )
    if entry["note"]:
        text += f"\n📝 {esc(entry['note'])}"
    return text


def change_account_keyboard(entry_id: int):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Change account", callback_data=f"chacc:{entry_id}")]]
    )


def budget_warning_text(warning) -> str:
    """The bot's wording for a warning from budgets.warning_for (shared with the Mini App)."""
    if not warning:
        return ""
    label = esc(warning["label"])
    spent, limit = warning["spent_minor"] / 100, warning["limit_minor"] / 100
    if warning["level"] == "over":
        return f"🚨 You're over budget on {label}: {spent:.2f} / {limit:.2f}"
    return f"⚠️ {warning['percent']}% of your {label} budget used ({spent:.2f} / {limit:.2f})"


async def _finalize(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str, type_: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    amount = context.user_data.pop("pending_amount")
    category_key = context.user_data.pop("pending_category")
    account_key = context.user_data.pop("pending_account", "cash")
    used_default = context.user_data.pop("used_default", False)
    entry, warning = await db_call(
        transactions.add_entry, user_id, to_minor(amount), type_, category_key, account_key, note
    )
    entry_id = entry["id"]
    text = entry_line(entry)
    if warning:
        text += "\n\n" + budget_warning_text(warning)

    if used_default:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=change_account_keyboard(entry_id))
        await context.bot.send_message(chat_id=chat_id, text="👇 Menu", reply_markup=main_menu_keyboard())
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def _flow_note_typed(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    note = update.message.text.strip()
    if len(note) > MAX_NOTE_LENGTH:
        await update.message.reply_text(
            f"Notes can be up to {MAX_NOTE_LENGTH} characters; yours has {len(note)}. "
            "Send a shorter one, or tap Skip.",
            reply_markup=note_keyboard(FLOW[type_]["skip"]),
        )
        return FLOW[type_]["states"][3]
    return await _finalize(update, context, note, type_)


async def _flow_note_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE, type_: str):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏭️ No note added.")
    return await _finalize(update, context, "", type_)


def _bind(fn, type_):
    async def handler(update, context):
        return await fn(update, context, type_)
    handler.__name__ = f"{fn.__name__}_{type_}"
    return handler


add_start = _bind(_flow_start, "expense")
add_amount_received = _bind(_flow_amount, "expense")
add_category_chosen = _bind(_flow_category, "expense")
add_account_chosen = _bind(_flow_account, "expense")
add_note_received = _bind(_flow_note_typed, "expense")
add_note_skipped = _bind(_flow_note_skipped, "expense")

add_income_start = _bind(_flow_start, "income")
add_income_amount_received = _bind(_flow_amount, "income")
add_income_category_chosen = _bind(_flow_category, "income")
add_income_account_chosen = _bind(_flow_account, "income")
add_income_note_received = _bind(_flow_note_typed, "income")
add_income_note_skipped = _bind(_flow_note_skipped, "income")


# ---------------------------------------------------------------------------
# Change the account of a saved entry (the default-account shortcut's undo)
# ---------------------------------------------------------------------------
async def change_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    entry_id = int(query.data.split(":", 1)[1])
    entry = await db_call(transactions.get_entry, update.effective_user.id, entry_id)
    if not entry:
        await query.answer("That entry was deleted.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_reply_markup(
        reply_markup=account_keyboard(f"setacc:{entry_id}", default=entry["account"], with_cancel=False, sep=":")
    )


async def change_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, entry_id, account_key = query.data.split(":", 2)
    entry_id = int(entry_id)
    user_id = update.effective_user.id
    if account_key not in dict(ACCOUNTS) or not await db_call(transactions.set_account, user_id, entry_id, account_key):
        await query.answer("That entry was deleted.", show_alert=True)
        return
    await query.answer(f"Moved to {account_label(account_key)}")
    entry = await db_call(transactions.get_entry, user_id, entry_id)
    await query.edit_message_text(entry_line(entry), reply_markup=change_account_keyboard(entry_id))


# ---------------------------------------------------------------------------
# Leaving a flow
# ---------------------------------------------------------------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_pending(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Cancelled.")
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Cancelled. Nothing was saved.", reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def stale_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A Cancel button from a flow that already ended."""
    await update.callback_query.answer("Nothing to cancel.")
    await update.callback_query.edit_message_reply_markup(reply_markup=None)


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_pending(context)
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⌛ That entry timed out and wasn't saved.",
            reply_markup=main_menu_keyboard(),
        )


async def leave_flow_for_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A menu button (or /start) tapped mid-flow: drop the half-finished entry and run that button."""
    clear_pending(context)
    text = update.message.text if update.message else ""
    view = {
        BTN_HISTORY: history_view,
        BTN_SUMMARY: summary_view,
        BTN_BUDGETS: budgets_view,
        BTN_ACCOUNTS: accounts_view,
        BTN_HELP: help_view,
    }.get(text, start)
    if view is not start and view is not help_view and view is not history_view:
        # These screens carry inline buttons, so bring the main keyboard back first.
        await update.message.reply_text("↩️ Unfinished entry dropped.", reply_markup=main_menu_keyboard())
    await view(update, context)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@require_subscription
async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db_call(transactions.list_recent, update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text(
            f"No transactions yet. Tap {BTN_ADD} or {BTN_ADD_INCOME} to log your first one.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await update.effective_message.reply_text("📋 <b>Recent transactions:</b>", reply_markup=main_menu_keyboard())
    for r in rows:
        date = r["created_at"][:10]
        type_ = r["type"]
        sign = "+" if type_ == "income" else MINUS
        note = f" — {esc(r['note'])}" if r["note"] else ""
        text = (
            f"{date}  {sign}{r['amount']:.2f}  {esc(label_for(r['category'], type_))} · "
            f"{esc(account_label(r['account']))}{note}"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{r['id']}"),
                                    InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{r['id']}")]])
        await update.effective_message.reply_text(text, reply_markup=kb)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    expense_id = int(query.data.split("_", 1)[1])
    ok = await db_call(transactions.delete_expense, update.effective_user.id, expense_id)
    await query.answer("Deleted" if ok else "Already gone")
    if ok:
        await query.edit_message_text("🗑️ Deleted.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
@require_subscription
async def summary_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("This Week", callback_data="sum_week"),
          InlineKeyboardButton("This Month", callback_data="sum_month")]]
    )
    await update.effective_message.reply_text("Pick a period:", reply_markup=kb)


def format_summary(data: dict) -> str:
    since = datetime.fromisoformat(data["from"])
    title = "This month" if data["period"] == "month" else "This week"
    income, expense, net = data["income_minor"] / 100, data["expense_minor"] / 100, data["net_minor"] / 100
    lines = [
        f"📊 <b>{title}</b> (since {since:%a %d %b})",
        f"💵 Income: {income:.2f}",
        f"💸 Expenses: {expense:.2f}",
        f"⚖️ Net: {net:+.2f}",
    ]
    if data["savings_rate"] is not None:
        lines.append(f"💹 Savings rate: {data['savings_rate']:.0f}%")
    lines.append("")
    if data["by_category"]:
        lines.append("<b>Expenses by category:</b>")
        for c in data["by_category"]:
            lines.append(f"• {esc(c['label'])}: {c['total_minor'] / 100:.2f} ({c['count']}x)")
    else:
        lines.append("No expenses in this period.")
    return "\n".join(lines)


async def summary_text(user_id: int, period: str) -> str:
    return format_summary(await db_call(summaries.summary, user_id, period))


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    period = query.data.split("_", 1)[1]
    await query.edit_message_text(await summary_text(update.effective_user.id, period))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@require_subscription
async def accounts_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balances = await db_call(accounts.account_balances, user_id)
    default_acc = await db_call(accounts.get_default_account, user_id)
    lines = ["🏦 <b>Account balances:</b>"]
    for key, label in ACCOUNTS:
        star = " ⭐" if key == default_acc else ""
        lines.append(f"• {esc(label)}: {balances.get(key, 0):+.2f}{star}")
    if default_acc:
        lines.append("\n⭐ = your default account. New entries go there without asking.")
    else:
        lines.append("\nSet a default account and new entries skip the account step.")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⭐ Set default account", callback_data="set_default_account_start")]]
    )
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


async def set_default_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Pick your default account:")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Choose one:",
        reply_markup=account_keyboard(
            "setdefacc", default=await db_call(accounts.get_default_account, update.effective_user.id), with_cancel=False
        ),
    )


async def set_default_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    await db_call(accounts.set_default_account, update.effective_user.id, account_key)
    await query.edit_message_text(f"⭐ Default account set to {esc(account_label(account_key))}")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@require_subscription
async def budgets_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db_call(budgets.get_budgets, update.effective_user.id)
    lines = ["💰 <b>Your monthly budgets:</b>"]
    if rows:
        lines += [f"• {esc(label_for(r['category'], 'expense'))}: {r['amount']:.2f}" for r in rows]
    else:
        lines.append("None set yet.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Set a budget", callback_data="set_budget_start")]])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


async def budget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_subscribed(context, query.from_user.id):
        await query.answer()
        await send_gate(update)
        return ConversationHandler.END
    clear_pending(context)
    await query.answer()
    await query.edit_message_text("Pick a category to set a budget for:")
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Choose one:", reply_markup=category_keyboard("budgetcat")
    )
    return BUDGET_CATEGORY


async def budget_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_budget_category"] = category_key
    await query.edit_message_text(f"Category: {esc(CATEGORY_LABELS[category_key])}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Type the monthly limit, e.g. 200",
        reply_markup=cancel_keyboard(),
    )
    return BUDGET_AMOUNT


async def budget_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except ValueError as e:
        await update.message.reply_text(f"{esc(e)} Try again, e.g. 200")
        return BUDGET_AMOUNT
    category_key = context.user_data.pop("pending_budget_category")
    await db_call(budgets.set_budget, update.effective_user.id, category_key, amount)
    await update.message.reply_text(
        f"✅ Budget for {esc(CATEGORY_LABELS[category_key])} set to {amount:.2f} a month",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
def is_admin(update: Update) -> bool:
    admin = config.ADMIN_CHAT_ID
    return admin is not None and admin in (update.effective_user.id, update.effective_chat.id)


async def recap_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: send the admin's own last-week recap to ADMIN_CHAT_ID, nobody else."""
    if not is_admin(update):
        return
    start, end = periods.previous_week()
    text = await db_call(recap_text, update.effective_user.id, start, end) or (
        f"📊 Recap preview: nothing logged between {start:%a %d %b} and {end:%a %d %b}."
    )
    await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=text)


async def backup_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: make a backup now and send it to ADMIN_CHAT_ID."""
    if not is_admin(update):
        return
    path = await run_backup(context.bot)
    await update.effective_message.reply_text(f"🗄️ Backup written: <code>{esc(path)}</code>")
