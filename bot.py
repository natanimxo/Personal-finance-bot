import os
import logging
from datetime import datetime, timedelta, time, timezone
from functools import wraps

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
REQUIRED_CHANNEL = os.environ["REQUIRED_CHANNEL"]
CHANNEL_INVITE_LINK = os.environ.get("CHANNEL_INVITE_LINK", "")

VALID_STATUSES = {"member", "administrator", "creator"}

# ---------------------------------------------------------------------------
# Menu layout
# ---------------------------------------------------------------------------
BTN_ADD = "➕ Add Expense"
BTN_ADD_INCOME = "💵 Add Income"
BTN_HISTORY = "📋 History"
BTN_SUMMARY = "📊 Summary"
BTN_BUDGETS = "💰 Budgets"
BTN_HELP = "❓ Help"

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


ASK_AMOUNT, ASK_CATEGORY, ASK_NOTE = range(3)
ASK_INCOME_AMOUNT, ASK_INCOME_CATEGORY, ASK_INCOME_NOTE = range(10, 13)
BUDGET_CATEGORY, BUDGET_AMOUNT = range(3, 5)


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_ADD, BTN_ADD_INCOME], [BTN_HISTORY, BTN_SUMMARY], [BTN_BUDGETS, BTN_HELP]],
        resize_keyboard=True,
    )


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


# ---------------------------------------------------------------------------
# Subscription gate
# ---------------------------------------------------------------------------
async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in VALID_STATUSES
    except Exception as e:
        logger.warning(f"Subscription check failed for {user_id}: {e}")
        return False


def gate_keyboard():
    buttons = []
    if CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton("📢 Join the channel", url=CHANNEL_INVITE_LINK)])
    buttons.append([InlineKeyboardButton("✅ I've subscribed", callback_data="recheck_sub")])
    return InlineKeyboardMarkup(buttons)


GATE_TEXT = (
    "🔒 *Welcome to your expense tracker!*\n\n"
    "Here's what I do:\n"
    "• Log spending in 3 taps\n"
    "• Warn you the moment you're near a budget\n"
    "• Send you a spending recap every Monday\n\n"
    "This bot is free — you just need to join my channel first:\n"
    f"{CHANNEL_INVITE_LINK}\n\n"
    "Then tap ✅ below."
)


async def send_gate(update: Update):
    await update.effective_message.reply_text(
        GATE_TEXT, reply_markup=gate_keyboard(), parse_mode=ParseMode.MARKDOWN
    )


def require_subscription(handler):
    """For simple, non-conversation button/command handlers."""
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user_id = update.effective_user.id
        if await is_subscribed(context, user_id):
            db.register_user(user_id)
            return await handler(update, context, *a, **kw)
        await send_gate(update)
    return wrapper


async def recheck_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_subscribed(context, user_id):
        db.register_user(user_id)
        await query.answer("You're in! 🎉")
        await query.edit_message_text("✅ Subscription confirmed! Here's your menu 👇")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Tap a button to get started.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("Still not subscribed — join the channel first.", show_alert=True)


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
        f"{BTN_BUDGETS} — set spending limits & get warned\n\n"
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
        "4️⃣ Add a note, or skip it\n\n"
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
    db.register_user(user_id)
    await update.message.reply_text(
        "💵 How much did you spend? (just type the number, e.g. 12.50)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_AMOUNT


async def add_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
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
    db.add_expense(user_id, amount, category_key, note, type_=type_)

    label = label_for(category_key, type_)
    sign = "+" if type_ == "income" else ""
    icon = "💵" if type_ == "income" else "✅"
    text = f"{icon} Logged {sign}{amount:.2f} — {label}" + (f"\n📝 {note}" if note else "")

    if type_ == "expense":
        budget = db.get_budget(user_id, category_key)
        if budget:
            month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            spent = db.month_total_for_category(user_id, category_key, month_start)
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
    db.register_user(user_id)
    await update.message.reply_text(
        "💵 How much did you receive? (just type the number, e.g. 500)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_INCOME_AMOUNT


async def add_income_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
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


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@require_subscription
async def history_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_recent(update.effective_user.id)
    if not rows:
        await update.message.reply_text(
            f"No expenses yet. Tap {BTN_ADD} to log your first one.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await update.message.reply_text("📋 *Recent expenses:*", parse_mode=ParseMode.MARKDOWN)
    for r in rows:
        date = r["created_at"][:10]
        type_ = r["type"] if "type" in r.keys() else "expense"
        label = label_for(r["category"], type_)
        sign = "+" if type_ == "income" else "-"
        note = f" — {r['note']}" if r["note"] else ""
        text = f"{date}  {sign}{r['amount']:.2f}  {label}{note}"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{r['id']}")]]
        )
        await update.message.reply_text(text, reply_markup=kb)


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    expense_id = int(query.data.split("_", 1)[1])
    ok = db.delete_expense(update.effective_user.id, expense_id)
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
                InlineKeyboardButton("This Week", callback_data="sum_week"),
                InlineKeyboardButton("This Month", callback_data="sum_month"),
            ]
        ]
    )
    await update.message.reply_text("Pick a period:", reply_markup=kb)


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    period = query.data.split("_", 1)[1]
    since = datetime.utcnow() - (timedelta(days=30) if period == "month" else timedelta(days=7))
    label = "month" if period == "month" else "week"

    income_total, expense_total = db.totals_since(update.effective_user.id, since)
    net = income_total - expense_total

    lines = [
        f"📊 *This {label}:*",
        f"💵 Income: {income_total:.2f}",
        f"💸 Expenses: {expense_total:.2f}",
        f"⚖️ Net Balance: {net:+.2f}",
        f"🏦 Savings: {net:+.2f}",
        "",
    ]

    rows, _ = db.summary_since(update.effective_user.id, since, type_="expense")
    if rows:
        lines.append("*Expenses by category:*")
        for r in rows:
            cat_label = CATEGORY_LABELS.get(r["category"], f"📦 {r['category']}")
            lines.append(f"• {cat_label}: {r['total']:.2f} ({r['cnt']}x)")
    else:
        lines.append("No expenses in this period.")

    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@require_subscription
async def budgets_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_budgets(update.effective_user.id)
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
    return BUDGET_AMOUNT


async def budget_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid amount — try again, e.g. 200")
        return BUDGET_AMOUNT
    category_key = context.user_data.pop("pending_budget_category")
    db.set_budget(update.effective_user.id, category_key, amount)
    await update.message.reply_text(
        f"✅ Budget for {CATEGORY_LABELS[category_key]} set to {amount:.2f}",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Weekly auto-recap
# ---------------------------------------------------------------------------
async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    since = datetime.utcnow() - timedelta(days=7)
    for user_id in db.get_all_users():
        if not await is_subscribed(context, user_id):
            continue
        income_total, expense_total = db.totals_since(user_id, since)
        rows, _ = db.summary_since(user_id, since, type_="expense")
        if not rows and income_total == 0:
            continue
        net = income_total - expense_total
        lines = [
            "📊 *Your weekly recap:*",
            f"💵 Income: {income_total:.2f}",
            f"💸 Expenses: {expense_total:.2f}",
            f"⚖️ Net Balance: {net:+.2f}",
            "",
        ]
        if rows:
            lines.append("*Top expense categories:*")
            for r in rows:
                cat_label = CATEGORY_LABELS.get(r["category"], f"📦 {r['category']}")
                lines.append(f"• {cat_label}: {r['total']:.2f} ({r['cnt']}x)")
        try:
            await context.bot.send_message(
                chat_id=user_id, text="\n".join(lines), parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Couldn't send recap to {user_id}: {e}")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HISTORY}$"), history_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SUMMARY}$"), summary_view))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BUDGETS}$"), budgets_view))

    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD}$"), add_start)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount_received)],
            ASK_CATEGORY: [CallbackQueryHandler(add_category_chosen, pattern="^addcat_")],
            ASK_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_received),
                CallbackQueryHandler(add_note_skipped, pattern="^skip_note$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(add_conv)

    add_income_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD_INCOME}$"), add_income_start)],
        states={
            ASK_INCOME_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_income_amount_received)],
            ASK_INCOME_CATEGORY: [CallbackQueryHandler(add_income_category_chosen, pattern="^inccat_")],
            ASK_INCOME_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_income_note_received),
                CallbackQueryHandler(add_income_note_skipped, pattern="^skip_income_note$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(add_income_conv)

    budget_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(budget_start, pattern="^set_budget_start$")],
        states={
            BUDGET_CATEGORY: [CallbackQueryHandler(budget_category_chosen, pattern="^budgetcat_")],
            BUDGET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_amount_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(budget_conv)

    app.add_handler(CallbackQueryHandler(recheck_sub_callback, pattern="^recheck_sub$"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(summary_callback, pattern="^sum_"))

    app.job_queue.run_daily(
        send_weekly_recap, time=time(hour=9, tzinfo=timezone.utc), days=(0,)
    )

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
