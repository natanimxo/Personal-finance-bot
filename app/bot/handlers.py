from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, ContextTypes, filters

from app.services import users, transactions, accounts, budgets, summaries
from app.bot.keyboards import *  # noqa: F401,F403  (menu constants, keyboards, labels, helpers)
from app.bot.keyboards import month_start
from app.bot.membership import is_subscribed, send_gate, require_subscription


# ---------------------------------------------------------------------------
# Start / Help
# ---------------------------------------------------------------------------
@require_subscription
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "I'm your expense tracker. Everything works through the buttons below "
        "— no typing commands needed.\n\n"
        f"{BTN_ADD} — log a spend in 3 taps\n"
        f"{BTN_ADD_INCOME} — log income in 3 taps\n"
        f"{BTN_HISTORY} — see your recent activity\n"
        f"{BTN_SUMMARY} — income, expenses & net balance\n"
        f"{BTN_BUDGETS} — set spending limits & get warned\n"
        f"{BTN_ACCOUNTS} — see balances across Cash/Bank/Card/Mobile Wallets\n\n"
        "I'll also message you automatically every Monday with a recap.",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


@require_subscription
async def help_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*How this works*\n\n"
        f"1️⃣ Tap {BTN_ADD} or {BTN_ADD_INCOME}\n"
        "2️⃣ Type the amount\n"
        "3️⃣ Tap a category button\n"
        "4️⃣ Tap an account (your ⭐ default is listed first)\n"
        "5️⃣ Add a note, or skip it\n\n"
        f"Changed your mind? Tap {BTN_CANCEL} or send /cancel at any step.\n\n"
        "That's it — it's saved. Use the other buttons any time to check your "
        "history, totals, or budgets.",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Add expense — guided conversation
# ---------------------------------------------------------------------------
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subscribed(context, user_id):
        await send_gate(update)
        return ConversationHandler.END
    users.register_user(user_id)
    await update.message.reply_text(
        "💵 How much did you spend? (just type the number, e.g. 12.50)",
        reply_markup=cancel_keyboard(),
    )
    return ASK_AMOUNT


async def add_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid amount — try again, e.g. 12.50")
        return ASK_AMOUNT
    context.user_data["pending_amount"] = amount
    await update.message.reply_text(
        "Pick a category:", reply_markup=category_keyboard("addcat")
    )
    return ASK_CATEGORY


async def add_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_category"] = category_key
    await query.edit_message_text(f"Category: {CATEGORY_LABELS[category_key]}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Which account?",
        reply_markup=account_keyboard("addacc", accounts.get_default_account(update.effective_user.id)),
    )
    return ASK_ACCOUNT


async def add_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    context.user_data["pending_account"] = account_key
    await query.edit_message_text(f"Account: {ACCOUNT_LABELS[account_key]}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Want to add a quick note? Type it, or tap Skip.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⏭️ Skip", callback_data="skip_note")]]
        ),
    )
    return ASK_NOTE


async def finalize_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str, chat_id: int, type_: str = "expense"):
    user_id = update.effective_user.id
    amount = context.user_data.pop("pending_amount")
    category_key = context.user_data.pop("pending_category")
    account_key = context.user_data.pop("pending_account", "cash")
    transactions.add_expense(user_id, amount, category_key, note, type_=type_, account=account_key)

    label = label_for(category_key, type_)
    account_label = ACCOUNT_LABELS.get(account_key, account_key)
    sign = "+" if type_ == "income" else ""
    icon = "💵" if type_ == "income" else "✅"
    text = f"{icon} Logged {sign}{amount:.2f} — {label} ({account_label})" + (f"\n📝 {note}" if note else "")

    if type_ == "expense":
        budget = budgets.get_budget(user_id, category_key)
        if budget:
            spent = budgets.month_total_for_category(user_id, category_key, month_start())
            pct = spent / budget * 100
            if spent > budget:
                text += f"\n\n🚨 You're over budget on {label}: {spent:.2f} / {budget:.2f}"
            elif pct >= 80:
                text += f"\n\n⚠️ {pct:.0f}% of your {label} budget used ({spent:.2f} / {budget:.2f})"

    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_keyboard())


async def add_note_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await finalize_expense(update, context, update.message.text.strip(), update.effective_chat.id)
    return ConversationHandler.END


async def add_note_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏭️ No note added.")
    await finalize_expense(update, context, "", update.effective_chat.id)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Add income — mirrors the expense flow above
# ---------------------------------------------------------------------------
async def add_income_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subscribed(context, user_id):
        await send_gate(update)
        return ConversationHandler.END
    users.register_user(user_id)
    await update.message.reply_text(
        "💵 How much did you receive? (just type the number, e.g. 500)",
        reply_markup=cancel_keyboard(),
    )
    return ASK_INCOME_AMOUNT


async def add_income_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid amount — try again, e.g. 500")
        return ASK_INCOME_AMOUNT
    context.user_data["pending_amount"] = amount
    await update.message.reply_text(
        "Pick a category:", reply_markup=income_category_keyboard("inccat")
    )
    return ASK_INCOME_CATEGORY


async def add_income_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_category"] = category_key
    await query.edit_message_text(f"Category: {INCOME_CATEGORY_LABELS[category_key]}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Which account?",
        reply_markup=account_keyboard("incacc", accounts.get_default_account(update.effective_user.id)),
    )
    return ASK_INCOME_ACCOUNT


async def add_income_account_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    context.user_data["pending_account"] = account_key
    await query.edit_message_text(f"Account: {ACCOUNT_LABELS[account_key]}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Want to add a quick note? Type it, or tap Skip.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⏭️ Skip", callback_data="skip_income_note")]]
        ),
    )
    return ASK_INCOME_NOTE


async def add_income_note_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await finalize_expense(update, context, update.message.text.strip(), update.effective_chat.id, type_="income")
    return ConversationHandler.END


async def add_income_note_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏭️ No note added.")
    await finalize_expense(update, context, "", update.effective_chat.id, type_="income")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⌛ That entry timed out and wasn't saved.",
            reply_markup=main_menu_keyboard(),
        )


async def leave_flow_for_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A menu button (or /start) tapped mid-flow: drop the half-finished entry and open that screen."""
    context.user_data.clear()
    text = update.message.text if update.message else ""
    view = {
        BTN_HISTORY: history_view,
        BTN_SUMMARY: summary_view,
        BTN_BUDGETS: budgets_view,
        BTN_ACCOUNTS: accounts_view,
        BTN_HELP: help_view,
    }.get(text)
    if view is None:  # /start, or Add Expense / Add Income tapped mid-flow
        return await cancel(update, context)
    await view(update, context)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@require_subscription
async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = transactions.list_recent(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            f"Nothing logged yet. Tap {BTN_ADD} or {BTN_ADD_INCOME} to log your first entry.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await update.message.reply_text("📋 *Recent activity:*", parse_mode=ParseMode.MARKDOWN)
    for r in rows:
        date = r["created_at"][:10]
        type_ = r["type"] if "type" in r.keys() else "expense"
        account_key = r["account"] if "account" in r.keys() else "cash"
        label = label_for(r["category"], type_)
        account_label = ACCOUNT_LABELS.get(account_key, account_key)
        sign = "+" if type_ == "income" else "-"
        note = f" — {r['note']}" if r["note"] else ""
        text = f"{date}  {sign}{r['amount']:.2f}  {label} · {account_label}{note}"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{r['id']}")]]
        )
        await update.message.reply_text(text, reply_markup=kb)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    expense_id = int(query.data.split("_", 1)[1])
    ok = transactions.delete_expense(update.effective_user.id, expense_id)
    await query.answer("Deleted" if ok else "Already gone")
    if ok:
        await query.edit_message_text("🗑️ Deleted.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
@require_subscription
async def summary_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Last 7 Days", callback_data="sum_week"),
                InlineKeyboardButton("This Month", callback_data="sum_month"),
            ]
        ]
    )
    await update.message.reply_text("Pick a period:", reply_markup=kb)


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    period = query.data.split("_", 1)[1]
    if period == "month":
        since, title = month_start(), "This month"
    else:
        since, title = datetime.utcnow() - timedelta(days=7), "Last 7 days"

    income_total, expense_total = summaries.totals_since(update.effective_user.id, since)
    net = income_total - expense_total

    lines = [
        f"📊 *{title}:*",
        f"💵 Income: {income_total:.2f}",
        f"💸 Expenses: {expense_total:.2f}",
        f"⚖️ Net Balance: {net:+.2f}",
        "",
    ]

    rows, _ = summaries.summary_since(update.effective_user.id, since, type_="expense")
    if rows:
        lines.append("*Expenses by category:*")
        for r in rows:
            cat_label = CATEGORY_LABELS.get(r["category"], f"📦 {r['category']}")
            lines.append(f"• {cat_label}: {r['total']:.2f} ({r['cnt']}x)")
    else:
        lines.append("No expenses in this period.")

    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@require_subscription
async def accounts_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balances = accounts.account_balances(user_id)
    default_acc = accounts.get_default_account(user_id)
    lines = ["🏦 *Account balances:*"]
    for key, label in ACCOUNTS:
        bal = balances.get(key, 0)
        star = " ⭐" if key == default_acc else ""
        lines.append(f"• {label}: {bal:+.2f}{star}")
    lines.append("\n⭐ = your default account")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⭐ Set default account", callback_data="set_default_account_start")]]
    )
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def set_default_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Pick your default account:")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Choose one:",
        reply_markup=account_keyboard("setdefacc"),
    )


async def set_default_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_key = query.data.split("_", 1)[1]
    accounts.set_default_account(update.effective_user.id, account_key)
    await query.edit_message_text(f"⭐ Default account set to {ACCOUNT_LABELS[account_key]}")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@require_subscription
async def budgets_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = budgets.get_budgets(update.effective_user.id)
    lines = ["💰 *Your budgets:*"]
    if rows:
        lines += [f"• {CATEGORY_LABELS.get(r['category'], r['category'])}: {r['amount']:.2f}" for r in rows]
    else:
        lines.append("None set yet.")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("➕ Set a budget", callback_data="set_budget_start")]]
    )
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def budget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await is_subscribed(context, user_id):
        await query.answer()
        await send_gate(update)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("Pick a category to set a budget for:")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Choose one:",
        reply_markup=category_keyboard("budgetcat"),
    )
    return BUDGET_CATEGORY


async def budget_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_key = query.data.split("_", 1)[1]
    context.user_data["pending_budget_category"] = category_key
    await query.edit_message_text(
        f"Category: {CATEGORY_LABELS[category_key]}\n\nType the monthly limit, e.g. 200"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"(Tap {BTN_CANCEL} to stop.)",
        reply_markup=cancel_keyboard(),
    )
    return BUDGET_AMOUNT


async def budget_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid amount — try again, e.g. 200")
        return BUDGET_AMOUNT
    category_key = context.user_data.pop("pending_budget_category")
    budgets.set_budget(update.effective_user.id, category_key, amount)
    await update.message.reply_text(
        f"✅ Budget for {CATEGORY_LABELS[category_key]} set to {amount:.2f}",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END
