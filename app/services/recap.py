import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.services import users, summaries
from app.bot.keyboards import CATEGORY_LABELS
from app.bot.membership import is_subscribed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weekly auto-recap
# ---------------------------------------------------------------------------
async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    since = datetime.utcnow() - timedelta(days=7)
    for user_id in users.get_all_users():
        if not await is_subscribed(context, user_id):
            continue
        income_total, expense_total = summaries.totals_since(user_id, since)
        rows, _ = summaries.summary_since(user_id, since, type_="expense")
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
