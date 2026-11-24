"""Weekly and monthly recaps, each arriving at 08:00 in the user's own timezone.

An hourly job (recap_tick) looks at every user with a recap switched on: when it
is Monday 08:00 or later where they live (the 1st for the monthly one), and the
recap for that period hasn't gone out yet, it is sent. The window closes 24
hours later, so a restart or a missed hour still delivers it, but a user who
turns the recap on mid-week doesn't get a stale one.

Sent at most RECAP_RATE messages a second (Telegram allows about 30), and each
user's last-sent marker is stored after their message goes out, so a restart in
the middle of a run carries on where it stopped instead of sending duplicates.
"""
import asyncio
import html
import logging
import time
from datetime import datetime, timedelta, timezone

from telegram.error import Forbidden
from telegram.ext import ContextTypes

from app.db import db_call
from app.services import categories, periods, prefs, summaries, users
from app.services.money import fmt
from app.strings import t

logger = logging.getLogger(__name__)

RECAP_RATE = 25  # messages per second, below Telegram's ~30/s broadcast limit
RECAP_HOUR = 8   # local time
WINDOW = timedelta(hours=24)


def _change(now: float, before: float, period: str) -> str:
    """" (↑ 12% vs the week before)" style comparison, or "" when there's nothing to compare."""
    if not before:
        return ""
    pct = round((now - before) / before * 100)
    if pct == 0:
        return t("recap.same", period=period)
    return t("recap.up" if pct > 0 else "recap.down", pct=abs(pct), period=period)


@periods.in_user_zone
def recap_text(user_id: int, start: datetime, end: datetime, kind: str = "weekly"):
    """HTML recap for start <= entry < end, compared with the period before it,
    or None when nothing was logged."""
    income_total, expense_total = summaries.totals_since(user_id, start, until=end)
    rows, _ = summaries.summary_since(user_id, start, type_="expense", until=end)
    if not rows and income_total == 0:
        return None
    if kind == "monthly":
        prev_start, prev_end = periods.previous_month(start)
        title, period = t("recap.monthly_title", start=start), t("recap.month")
    else:
        prev_start, prev_end = start - timedelta(days=7), start
        last_day = end - timedelta(days=1)
        title, period = t("recap.weekly_title", start=start, last=last_day), t("recap.week")
    prev_income, prev_expense = summaries.totals_since(user_id, prev_start, until=prev_end)

    currency = prefs.get_prefs(user_id)["currency"]
    m = lambda amount, sign=False: fmt(round(amount * 100), currency, sign)  # noqa: E731
    net = income_total - expense_total
    lines = [
        title,
        t("recap.income", amount=m(income_total), change=_change(income_total, prev_income, period)),
        t("recap.expenses", amount=m(expense_total), change=_change(expense_total, prev_expense, period)),
        t("recap.net", amount=m(net, True)),
    ]
    rate = periods.savings_rate(income_total, expense_total)
    if rate is not None:
        lines.append(t("recap.savings_rate", rate=rate))
    if rows:
        top = rows[0]
        top_label = html.escape(categories.label(user_id, "expense", top["category"]), quote=False)
        share = round(top["total"] / expense_total * 100) if expense_total else 0
        lines += ["", t("recap.top", label=top_label, amount=m(top["total"]), share=share)]
        if len(rows) > 1:
            lines.append(t("recap.all_categories"))
            for r in rows:
                label = categories.label(user_id, "expense", r["category"])
                lines.append(t("recap.category_line", label=html.escape(label, quote=False), amount=m(r["total"]),
                               count=r["cnt"]))
    return "\n".join(lines)


def period_for(kind: str, now: datetime = None):
    """(start, end) of the period this recap covers, in the zone in force."""
    return periods.previous_month(now) if kind == "monthly" else periods.previous_week(now)


def due_key(kind: str, now: datetime = None):
    """The period key (its first day) when this recap is due now in the zone in force, else None.
    Due from 08:00 on Monday (weekly) or the 1st (monthly), for 24 hours."""
    local = periods.now_local(now)
    opens = (periods.month_start(now) if kind == "monthly" else periods.week_start(now)) + timedelta(hours=RECAP_HOUR)
    if not opens <= local < opens + WINDOW:
        return None
    return period_for(kind, now)[0].date().isoformat()


def due_users(kind: str, now: datetime = None):
    """[(user_id, zone, period_key)] whose recap is due now and not yet sent."""
    by_zone = {}
    for user_id, zone, last_sent in users.recap_rows(kind):
        if zone not in by_zone:
            with periods.use_zone(zone):
                by_zone[zone] = due_key(kind, now)
        key = by_zone[zone]
        if key and last_sent != key:
            yield user_id, zone, key


async def run_recap(context: ContextTypes.DEFAULT_TYPE, now: datetime = None, rate: float = None,
                    kind: str = "weekly") -> dict:
    """Send the weekly (or monthly) recap to everyone it is due for now. Returns counts."""
    from app.bot.membership import forget_active, is_subscribed  # bot side, imported late

    rate = rate or RECAP_RATE
    stats = {"sent": 0, "empty": 0, "not_subscribed": 0, "blocked": 0, "failed": 0}
    interval = 1.0 / rate
    next_send = time.monotonic()

    for user_id, zone, key in await db_call(lambda: list(due_users(kind, now))):
        if not await is_subscribed(context, user_id):
            stats["not_subscribed"] += 1
            continue
        with periods.use_zone(zone, user_id):
            start, end = period_for(kind, now)
            text = await db_call(recap_text, user_id, start, end, kind)
        if not text:
            await db_call(users.mark_recap_sent, user_id, key, kind)
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
        await db_call(users.mark_recap_sent, user_id, key, kind)
        stats["sent"] += 1

    if any(stats.values()):
        logger.info("%s recap: %s", kind.capitalize(), stats)
    return stats


async def recap_tick(context: ContextTypes.DEFAULT_TYPE):
    """Every hour, on the hour: whoever's Monday 08:00 (or the 1st) it is now gets their recap."""
    now = datetime.now(timezone.utc)
    await run_recap(context, now=now, kind="weekly")
    await run_recap(context, now=now, kind="monthly")
