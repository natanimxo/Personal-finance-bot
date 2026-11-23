"""The weekly recap: last Monday-to-Sunday week, sent Monday morning in APP_TIMEZONE."""
import html
import logging
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from app.services import periods, summaries, users

logger = logging.getLogger(__name__)

# Kept here (not imported from the bot package) so the service layer has no bot dependency.
CATEGORY_LABELS = {
    "food": "🍔 Food", "transport": "🚗 Transport", "bills": "🧾 Bills",
    "shopping": "🛍️ Shopping", "fun": "🎉 Fun", "other": "📦 Other",
}


def recap_text(user_id: int, start: datetime, end: datetime):
    """HTML recap for start <= entry < end, or None when nothing was logged."""
    income_total, expense_total = summaries.totals_since(user_id, start, until=end)
    rows, _ = summaries.summary_since(user_id, start, type_="expense", until=end)
    if not rows and income_total == 0:
        return None
    net = income_total - expense_total
    last_day = end - timedelta(days=1)
    lines = [
        f"📊 <b>Your weekly recap</b> ({start:%a %d %b} – {last_day:%a %d %b})",
        f"💵 Income: {income_total:.2f}",
        f"💸 Expenses: {expense_total:.2f}",
        f"⚖️ Net: {net:+.2f}",
    ]
    rate = periods.savings_rate(income_total, expense_total)
    if rate is not None:
        lines.append(f"💹 Savings rate: {rate:.0f}%")
    if rows:
        lines += ["", "<b>Top expense categories:</b>"]
        for r in rows:
            label = CATEGORY_LABELS.get(r["category"], f"📦 {r['category']}")
            lines.append(f"• {html.escape(label, quote=False)}: {r['total']:.2f} ({r['cnt']}x)")
    return "\n".join(lines)


async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    from app.bot.membership import is_subscribed  # bot-side check, imported late to keep layers apart

    start, end = periods.previous_week()
    for user_id in users.get_all_users():
        if not await is_subscribed(context, user_id):
            continue
        text = recap_text(user_id, start, end)
        if not text:
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            logger.warning(f"Couldn't send recap to {user_id}: {e}")
