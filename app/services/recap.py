"""The weekly recap: last Monday-to-Sunday week, sent Monday morning in APP_TIMEZONE.

Sent at most RECAP_RATE messages a second (Telegram allows about 30), and each
user's last_recap_sent is stored after their message goes out, so a restart in
the middle of a run carries on where it stopped instead of sending duplicates.
"""
import asyncio
import html
import logging
import time
from datetime import datetime, timedelta

from telegram.error import Forbidden
from telegram.ext import ContextTypes

from app.db import db_call
from app.services import periods, summaries, users

logger = logging.getLogger(__name__)

RECAP_RATE = 25  # messages per second, below Telegram's ~30/s broadcast limit

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


async def run_recap(context: ContextTypes.DEFAULT_TYPE, now: datetime = None, rate: float = None) -> dict:
    """Send last week's recap to everyone due one. Returns counts, for logs and tests."""
    from app.bot.membership import forget_active, is_subscribed  # bot side, imported late

    rate = rate or RECAP_RATE
    start, end = periods.previous_week(now)
    week_key = start.date().isoformat()
    stats = {"sent": 0, "empty": 0, "not_subscribed": 0, "blocked": 0, "failed": 0}
    interval = 1.0 / rate
    next_send = time.monotonic()

    for user_id in await db_call(users.recap_candidates, week_key):
        if not await is_subscribed(context, user_id):
            stats["not_subscribed"] += 1
            continue
        text = await db_call(recap_text, user_id, start, end)
        if not text:
            await db_call(users.mark_recap_sent, user_id, week_key)
            stats["empty"] += 1
            continue

        delay = next_send - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        next_send = max(next_send, time.monotonic()) + interval
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
        except Forbidden:
            # The user blocked the bot: stop messaging them until they write again.
            await db_call(users.mark_inactive, user_id)
            forget_active(user_id)
            stats["blocked"] += 1
            continue
        except Exception as e:
            logger.warning(f"Couldn't send recap to {user_id}: {e}")
            stats["failed"] += 1
            continue
        await db_call(users.mark_recap_sent, user_id, week_key)
        stats["sent"] += 1

    logger.info("Weekly recap for week of %s: %s", week_key, stats)
    return stats


async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    await run_recap(context)
