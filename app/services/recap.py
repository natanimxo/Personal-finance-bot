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
from app.services import periods, prefs, summaries, users
from app.services.money import fmt
from app.services import categories

logger = logging.getLogger(__name__)

RECAP_RATE = 25  # messages per second, below Telegram's ~30/s broadcast limit

def _change(now: float, before: float, period: str) -> str:
    """" (↑ 12% vs the week before)" style comparison, or "" when there's nothing to compare."""
    if not before:
        return ""
    pct = round((now - before) / before * 100)
    if pct == 0:
        return f" (same as the {period} before)"
    return f" ({'↑' if pct > 0 else '↓'} {abs(pct)}% vs the {period} before)"


def recap_text(user_id: int, start: datetime, end: datetime, kind: str = "weekly"):
    """HTML recap for start <= entry < end, compared with the period before it,
    or None when nothing was logged."""
    income_total, expense_total = summaries.totals_since(user_id, start, until=end)
    rows, _ = summaries.summary_since(user_id, start, type_="expense", until=end)
    if not rows and income_total == 0:
        return None
    if kind == "monthly":
        prev_start, prev_end = periods.previous_month(start)
        title, period = f"🗓️ <b>Your {start:%B} recap</b>", "month"
    else:
        prev_start, prev_end = start - timedelta(days=7), start
        last_day = end - timedelta(days=1)
        title, period = f"📊 <b>Your weekly recap</b> ({start:%a %d %b} – {last_day:%a %d %b})", "week"
    prev_income, prev_expense = summaries.totals_since(user_id, prev_start, until=prev_end)

    currency = prefs.get_prefs(user_id)["currency"]
    m = lambda amount, sign=False: fmt(round(amount * 100), currency, sign)  # noqa: E731
    net = income_total - expense_total
    lines = [
        title,
        f"💵 Income: {m(income_total)}{_change(income_total, prev_income, period)}",
        f"💸 Expenses: {m(expense_total)}{_change(expense_total, prev_expense, period)}",
        f"⚖️ Net: {m(net, True)}",
    ]
    rate = periods.savings_rate(income_total, expense_total)
    if rate is not None:
        lines.append(f"💹 Savings rate: {rate:.0f}%")
    if rows:
        top = rows[0]
        top_label = html.escape(categories.label(user_id, "expense", top["category"]), quote=False)
        share = round(top["total"] / expense_total * 100) if expense_total else 0
        lines += ["", f"🏆 Top category: {top_label}, {m(top['total'])} ({share}% of spending)"]
        if len(rows) > 1:
            lines.append("<b>All categories:</b>")
            for r in rows:
                label = categories.label(user_id, "expense", r["category"])
                lines.append(f"• {html.escape(label, quote=False)}: {m(r['total'])} ({r['cnt']}x)")
    return "\n".join(lines)


async def run_recap(context: ContextTypes.DEFAULT_TYPE, now: datetime = None, rate: float = None,
                    kind: str = "weekly") -> dict:
    """Send last week's (or last month's) recap to everyone due one. Returns counts."""
    from app.bot.membership import forget_active, is_subscribed  # bot side, imported late

    rate = rate or RECAP_RATE
    start, end = periods.previous_month(now) if kind == "monthly" else periods.previous_week(now)
    week_key = start.date().isoformat()
    stats = {"sent": 0, "empty": 0, "not_subscribed": 0, "blocked": 0, "failed": 0}
    interval = 1.0 / rate
    next_send = time.monotonic()

    for user_id in await db_call(users.recap_candidates, week_key, kind):
        if not await is_subscribed(context, user_id):
            stats["not_subscribed"] += 1
            continue
        text = await db_call(recap_text, user_id, start, end, kind)
        if not text:
            await db_call(users.mark_recap_sent, user_id, week_key, kind)
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
        await db_call(users.mark_recap_sent, user_id, week_key, kind)
        stats["sent"] += 1

    logger.info("%s recap for the period from %s: %s", kind.capitalize(), week_key, stats)
    return stats


async def send_weekly_recap(context: ContextTypes.DEFAULT_TYPE):
    await run_recap(context)


async def send_monthly_recap(context: ContextTypes.DEFAULT_TYPE):
    await run_recap(context, kind="monthly")
