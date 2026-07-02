import os
import logging
from datetime import datetime, timedelta
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Your channel's @username (public) or numeric chat id (for private channels), e.g. "@mychannel" or -1001234567890
REQUIRED_CHANNEL = os.environ["REQUIRED_CHANNEL"]
CHANNEL_INVITE_LINK = os.environ.get("CHANNEL_INVITE_LINK", "")  # optional, shown in the gate message

VALID_STATUSES = {"member", "administrator", "creator"}


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in VALID_STATUSES
    except Exception as e:
        logger.warning(f"Subscription check failed for {user_id}: {e}")
        # Fail closed: if we can't verify, don't let them in
        return False


def gate_keyboard():
    buttons = []
    if CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton("📢 Join the channel", url=CHANNEL_INVITE_LINK)])
    buttons.append([InlineKeyboardButton("✅ I've subscribed", callback_data="recheck_sub")])
    return InlineKeyboardMarkup(buttons)


def require_subscription(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user_id = update.effective_user.id
        if await is_subscribed(context, user_id):
            return await handler(update, context, *a, **kw)
        await update.effective_message.reply_text(
            "🔒 This bot is free to use, but you need to subscribe to my channel first.\n\n"
            "Join, then tap the button below to unlock it.",
            reply_markup=gate_keyboard(),
        )
    return wrapper


async def recheck_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_subscribed(context, user_id):
        await query.answer("You're in! 🎉")
        await query.edit_message_text(
            "✅ Subscription confirmed! Send /help to see what I can do."
        )
    else:
        await query.answer("Still not subscribed — join the channel first.", show_alert=True)


@require_subscription
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! I'm your personal finance tracker.\n\n"
        "Send /help to see all commands."
    )


@require_subscription
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Commands*\n\n"
        "`/add 12.50 food lunch` — log an expense (amount, category, optional note)\n"
        "`/list` — show your 10 most recent expenses\n"
        "`/delete 7` — delete expense with id 7\n"
        "`/summary` — this week's spending by category\n"
        "`/summary month` — this month's spending by category\n"
        "`/setbudget food 200` — set a monthly budget for a category\n"
        "`/budgets` — view your budgets\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@require_subscription
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add <amount> <category> [note]")
        return
    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number, e.g. /add 12.50 food lunch")
        return
    category = args[1]
    note = " ".join(args[2:]) if len(args) > 2 else ""
    db.add_expense(update.effective_user.id, amount, category, note)
    await update.message.reply_text(f"✅ Logged {amount:.2f} under '{category}'" + (f" — {note}" if note else ""))


@require_subscription
async def list_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_recent(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No expenses logged yet. Try /add 10 food coffee")
        return
    lines = ["*Recent expenses:*"]
    for r in rows:
        date = r["created_at"][:10]
        note = f" — {r['note']}" if r["note"] else ""
        lines.append(f"`#{r['id']}` {date}  {r['amount']:.2f}  [{r['category']}]{note}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@require_subscription
async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete <id>")
        return
    try:
        expense_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return
    ok = db.delete_expense(update.effective_user.id, expense_id)
    await update.message.reply_text("🗑️ Deleted." if ok else "Couldn't find that expense.")


@require_subscription
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period = context.args[0].lower() if context.args else "week"
    since = datetime.utcnow() - (timedelta(days=30) if period == "month" else timedelta(days=7))
    rows, total = db.summary_since(update.effective_user.id, since)
    if not rows:
        await update.message.reply_text("No expenses in this period.")
        return
    label = "month" if period == "month" else "week"
    lines = [f"*Spending this {label}:* {total:.2f} total\n"]
    for r in rows:
        lines.append(f"• {r['category']}: {r['total']:.2f} ({r['cnt']}x)")

    budgets = {b["category"]: b["amount"] for b in db.get_budgets(update.effective_user.id)}
    warnings = []
    for r in rows:
        cap = budgets.get(r["category"])
        if cap and r["total"] > cap:
            warnings.append(f"⚠️ Over budget on {r['category']}: {r['total']:.2f} / {cap:.2f}")
    if warnings:
        lines.append("")
        lines.extend(warnings)

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@require_subscription
async def setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /setbudget <category> <amount>")
        return
    category = args[0]
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return
    db.set_budget(update.effective_user.id, category, amount)
    await update.message.reply_text(f"✅ Budget for '{category}' set to {amount:.2f}")


@require_subscription
async def budgets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_budgets(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No budgets set yet. Try /setbudget food 200")
        return
    lines = ["*Your budgets:*"] + [f"• {r['category']}: {r['amount']:.2f}" for r in rows]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_recent))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("setbudget", setbudget))
    app.add_handler(CommandHandler("budgets", budgets))
    app.add_handler(CallbackQueryHandler(recheck_sub_callback, pattern="^recheck_sub$"))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
