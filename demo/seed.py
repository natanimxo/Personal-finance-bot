"""Fill demo/demo.db with about three months of believable data for one demo user.

    python demo/seed.py [--currency USD] [--seed 7] [--today 2026-11-28] [--scale 1.0] [--timezone Europe/Berlin]

Local only: it works on demo/demo.db (config.DEMO_DB), deletes it first, and refuses to run
next to Railway variables or the /data volume. The same flags always give the same data.

The story it tells: a monthly salary of 3,200 on the 1st (plus a few freelance payments
and one gift), rent of 1,100 on the 1st, everyday spending with natural weekday rhythm
(coffee and lunches on weekdays, groceries and dinners out on weekends), two
subscriptions, bills, shopping. Every full month ends with a savings rate of about
18-25%. Accounts get sensible balances (cash from ATM withdrawals, a wallet topped up
when needed, a card paid off weekly). Budgets are set so Food is about 70% used,
Shopping about 95% (its bar shows the warning colour) and Transport about 40%, whatever
day of the month you run it.
"""
import argparse
import calendar
import math
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Run as a script, the demo switch is set before the app is imported, so the app's own
# guard applies: it refuses to run next to Railway variables or the /data volume.
if __name__ == "__main__":
    os.environ.setdefault("DEMO_MODE", "true")

from app import config  # noqa: E402

# What a currency's amounts are multiplied by (the base numbers are US dollars), and a
# timezone to match. Anything else: --scale and --timezone.
SCALES = {"USD": 1, "EUR": 1, "GBP": 0.85, "CAD": 1.3, "AUD": 1.4, "INR": 80, "KES": 130, "NGN": 1500, "ETB": 55}
ZONES = {"USD": "America/New_York", "EUR": "Europe/Berlin", "GBP": "Europe/London", "CAD": "America/Toronto",
         "AUD": "Australia/Sydney", "INR": "Asia/Kolkata", "KES": "Africa/Nairobi", "NGN": "Africa/Lagos",
         "ETB": "Africa/Addis_Ababa"}

SALARY = 3200
RENT = 1100
# (day of month, amount, note) of money that comes in, by how many months back from "today"
FREELANCE = {
    3: [(14, 300, "Freelance: website fixes")],
    2: [(8, 400, "Logo design for Maya"), (22, 300, "Freelance: product photos")],
    1: [(11, 250, "Freelance: landing page copy")],
    0: [(2, 600, "Freelance: brand identity")],   # plus a payment that landed this week: see freelance_plan()
}
GIFTS = {2: [(15, 120, "Birthday gift from Grandma")]}
# What each month's expenses are aiming for: (1 - savings rate) of that month's income
SAVINGS_RATE = {3: 0.20, 2: 0.19, 1: 0.22, 0: 0.18}

# Bills and subscriptions: (day of month, amount, category, account, note)
FIXED = [
    (1, RENT, "bills", "bank", "Rent"),
    (3, 35, "fun", "card", "Gym membership"),
    (6, 2.99, "bills", "card", "iCloud storage"),
    (9, 15.49, "fun", "card", "Netflix"),
    (12, 54.90, "bills", "bank", "Internet"),
    (14, 10.99, "fun", "card", "Spotify"),
    (18, 39.00, "bills", "bank", "Phone plan"),
    (20, None, "bills", "bank", "Electricity"),     # varies a little
    (25, 28.50, "bills", "bank", "Water"),
]
ELECTRICITY = (62, 91)

# Everyday spending. (weekday: Monday = 0), probability, amount range, category, accounts, notes
COFFEE = ["Morning coffee", "Coffee", "Flat white", "Coffee with a colleague"]
LUNCH = ["Lunch at the deli", "Lunch with Sam", "Sandwich and soup", "Poke bowl", "Lunch with the team"]
DINNER = ["Dinner with Maya", "Pizza night", "Sushi with the team", "Brunch with Sam", "Thai takeout", "Dinner at Luigi's"]
SHOPPING = ["Running socks", "Phone case", "Books", "Houseplant", "Kitchen supplies", "T-shirt", "Notebook and pens"]
BIG_SHOPPING = ["New sneakers", "Winter jacket", "Headphones", "Desk lamp"]
TOP_UPS = [  # (category, probability weight, low, high, notes)
    ("fun", 5, 13, 28, ["Movie night", "Bowling with friends", "Board game cafe"]),
    ("fun", 4, 20, 48, ["Drinks with friends", "Karaoke night"]),
    ("fun", 2, 60, 110, ["Concert tickets", "Comedy show tickets"]),
    ("other", 3, 12, 30, ["Pharmacy", "Dry cleaning", "Haircut tip"]),
    ("other", 2, 28, 42, ["Haircut"]),
    ("other", 2, 35, 70, ["Gift for Mom", "Flowers for Sam's birthday"]),
]
WEEKEND_GETAWAY = (140, 260, "Weekend getaway")


def freelance_plan(today: date) -> dict:
    """FREELANCE, plus one more payment this month that always lands inside the current week
    (so the week view has income in it, whichever day you run this)."""
    paid = today - timedelta(days=min(2, today.weekday()))
    if paid.month != today.month:
        paid = today
    plan = {back: list(payments) for back, payments in FREELANCE.items()}
    plan[0].append((paid.day, 450, "Freelance: social graphics"))
    return plan


def amount_minor(base: float, scale: float) -> int:
    """A base (US dollar) amount as integer minor units of the chosen currency."""
    if scale >= 5:                       # big currencies: whole tens, no cents
        return int(round(base * scale / 10)) * 10 * 100
    return int(round(base * scale * 100))


def start_date(today: date) -> date:
    """The 1st of the month two (or, early in a month, three) months back: 2.5 to 3.5 months of data."""
    months_back = 2 if today.day >= 15 else 3
    year, month = today.year, today.month - months_back
    while month < 1:
        month, year = month + 12, year - 1
    return date(year, month, 1)


def months_back(day: date, today: date) -> int:
    return (today.year - day.year) * 12 + today.month - day.month


def days_in(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def month_days(start: date, today: date):
    """{months back: [days of that month that are in range]}"""
    result = {}
    day = start
    while day <= today:
        result.setdefault(months_back(day, today), []).append(day)
        day += timedelta(days=1)
    return result


def make_items(today: date, start: date, rng: random.Random) -> list:
    """Every income and expense, as dicts (type, day, base amount, category, account, note),
    before the accounts' cash and wallet top-ups are worked out."""
    items = []
    by_month = month_days(start, today)
    freelance = freelance_plan(today)
    income_full = {}
    for back in by_month:
        gifts = sum(a for _, a, _ in GIFTS.get(back, []))
        income_full[back] = SALARY + sum(a for _, a, _ in freelance.get(back, [])) + gifts

    for back, days in sorted(by_month.items(), reverse=True):
        first = days[0]
        in_range = {d.day for d in days}
        # --- money in -------------------------------------------------------------------------
        if 1 in in_range:
            items.append(dict(type="income", day=first.replace(day=1), amount=SALARY, category="salary",
                              account="bank", note="Monthly salary"))
        for day_no, amount, note in freelance.get(back, []):
            if day_no in in_range:
                items.append(dict(type="income", day=first.replace(day=day_no), amount=amount, category="freelance",
                                  account="bank", note=note))
        for day_no, amount, note in GIFTS.get(back, []):
            if day_no in in_range:
                items.append(dict(type="income", day=first.replace(day=day_no), amount=amount, category="gift",
                                  account="bank", note=note))
        # --- bills and subscriptions ----------------------------------------------------------
        fixed_expected = 0.0
        for day_no, amount, category, account, note in FIXED:
            expected = amount if amount is not None else sum(ELECTRICITY) / 2
            fixed_expected += expected
            if day_no in in_range:
                value = amount if amount is not None else round(rng.uniform(*ELECTRICITY), 2)
                items.append(dict(type="expense", day=first.replace(day=day_no), amount=value, category=category,
                                  account=account, note=note))
        # --- everyday spending: natural weekday rhythm ---------------------------------------
        daily = []
        for day in days:
            wd = day.weekday()
            if wd < 5:
                if rng.random() < 0.8:
                    daily.append(dict(day=day, amount=rng.uniform(4.25, 5.9), category="food",
                                      account=rng.choices(["card", "cash", "mobile_money"], [5, 3, 2])[0],
                                      note=rng.choice(COFFEE)))
                if rng.random() < 0.5:
                    daily.append(dict(day=day, amount=rng.uniform(9, 16.5), category="food",
                                      account=rng.choices(["card", "cash"], [6, 4])[0], note=rng.choice(LUNCH)))
            if wd == 5:
                daily.append(dict(day=day, amount=rng.uniform(78, 122), category="food", account="card",
                                  note="Weekly groceries"))
                if rng.random() < 0.4:
                    daily.append(dict(day=day, amount=rng.uniform(22, 70), category="shopping", account="card",
                                      note=rng.choice(SHOPPING)))
            if wd == 2 and rng.random() < 0.9:
                daily.append(dict(day=day, amount=rng.uniform(22, 44), category="food",
                                  account=rng.choice(["card", "cash"]), note="Groceries top-up"))
            if wd in (4, 5, 6) and rng.random() < {4: 0.7, 5: 0.8, 6: 0.5}[wd]:
                daily.append(dict(day=day, amount=rng.uniform(24, 58), category="food", account="card",
                                  note=rng.choice(DINNER)))
            if wd in (4, 5) and rng.random() < 0.55:
                daily.append(dict(day=day, amount=rng.uniform(12, 26), category="transport",
                                  account=rng.choices(["mobile_money", "card"], [7, 3])[0], note="Uber home"))
            if day.day in (3, 17):
                daily.append(dict(day=day, amount=30, category="transport", account="mobile_money",
                                  note="Metro card top-up"))
            if wd == 6 and rng.random() < 0.3:
                daily.append(dict(day=day, amount=rng.uniform(55, 100), category="transport", account="card",
                                  note="Train tickets"))
            if wd == 5 and rng.random() < 0.18:
                daily.append(dict(day=day, amount=rng.uniform(13, 28), category="fun", account="card",
                                  note="Movie night"))
            if rng.random() < 0.04:
                daily.append(dict(day=day, amount=rng.uniform(8, 27), category="other", account="cash",
                                  note="Pharmacy"))
        if len(days) >= 20:                                # about one bigger purchase a month
            weekend = [d for d in days if d.weekday() == 5 and d.day > 5]
            if weekend and rng.random() < 0.9:
                daily.append(dict(day=rng.choice(weekend), amount=rng.uniform(80, 130), category="shopping",
                                  account="card", note=rng.choice(BIG_SHOPPING)))
        # --- fit the month to its savings rate --------------------------------------------------
        full_variable = income_full[back] * (1 - SAVINGS_RATE[back]) - fixed_expected
        allowance = full_variable * len(days) / days_in(first)
        spent = sum(d["amount"] for d in daily)
        if spent > allowance > 0:                      # a touch too lavish: scale it down
            factor = max(0.7, allowance / spent)
            for d in daily:
                d["amount"] = round(d["amount"] * factor, 2)
        elif spent < allowance:                        # room left: fun and other things come up
            shortfall = allowance - spent
            weekend_days = [d for d in days if d.weekday() >= 5] or days
            if shortfall > 160 and rng.random() < 0.9:
                weekend_pick = [d for d in weekend_days if d.day > 3] or weekend_days
                value = round(min(rng.uniform(WEEKEND_GETAWAY[0], WEEKEND_GETAWAY[1]), shortfall), 2)
                daily.append(dict(day=rng.choice(weekend_pick), amount=value, category="fun", account="card",
                                  note=WEEKEND_GETAWAY[2]))
                shortfall -= value
            for _ in range(40):
                if shortfall < 12:
                    break
                category, _, low, high, notes = rng.choices(TOP_UPS, [t[1] for t in TOP_UPS])[0]
                value = round(min(rng.uniform(low, high), shortfall), 2)
                day = rng.choice(weekend_days if rng.random() < 0.6 else days)
                daily.append(dict(day=day, amount=value, category=category,
                                  account=rng.choices(["card", "cash", "mobile_money"], [6, 2, 2])[0],
                                  note=rng.choice(notes)))
                shortfall -= value
        for d in daily:
            items.append(dict(type="expense", **d))

    # --- make sure the three budgeted categories and "today" have something in them --------------
    this_month = [i for i in items if i["type"] == "expense" and months_back(i["day"], today) == 0]
    for category, note, value, account in (("food", "Weekly groceries", 84, "card"),
                                           ("transport", "Uber home", 18, "mobile_money"),
                                           ("shopping", "New sneakers", 88, "card")):
        if not any(i["category"] == category for i in this_month):
            items.append(dict(type="expense", day=today, amount=value, category=category, account=account, note=note))
    if not any(i["day"] == today for i in items):
        items.append(dict(type="expense", day=today, amount=4.8, category="food", account="card", note="Coffee"))
    return items


BUDGET_LIMITS = {"food": 1500, "transport": 750, "shopping": 225}      # monthly limits in USD terms
BUDGET_USED = {"food": 0.70, "transport": 0.40, "shopping": 0.96}      # how much of each this month shows


def fit_budgets(items: list, today: date) -> bool:
    """Nudge this month's food / transport / shopping so the tidy limits show 70% / 40% / 96% used.

    Works on whatever day it is run, as long as the month has enough spending to scale (otherwise
    False: the limits are then derived from the spending instead). Amounts are in base (USD) units.
    """
    groups = {}
    for item in items:
        if item["type"] == "expense" and months_back(item["day"], today) == 0 and item["category"] in BUDGET_LIMITS:
            groups.setdefault(item["category"], []).append(item)
    factors = {}
    for category, rows in groups.items():
        total = sum(r["amount"] for r in rows)
        factors[category] = BUDGET_LIMITS[category] * BUDGET_USED[category] / total if total else 0
    if set(factors) != set(BUDGET_LIMITS) or not all(0.75 <= f <= 1.3 for f in factors.values()):
        return False
    for category, rows in groups.items():
        target = round(BUDGET_LIMITS[category] * BUDGET_USED[category], 2)
        for r in rows:
            r["amount"] = round(r["amount"] * factors[category], 2)
        rows[-1]["amount"] = round(rows[-1]["amount"] + target - sum(r["amount"] for r in rows), 2)
    return True


def build(today: date, currency: str = "USD", rng_seed: int = 7, scale: float = None, timezone: str = None,
          user_id: int = None, reset: bool = True) -> dict:
    """Create the demo data in config.DB_PATH. Returns a summary (used by the tests)."""
    problems = config.demo_problems(os.environ)
    path = os.path.abspath(config.DB_PATH)
    for candidate in (str(config.DB_PATH), path):
        text = candidate.replace("\\", "/")
        if text == "/data" or text.startswith("/data/"):
            problems.append(f"the database path is {candidate}")
            break
    if problems:
        raise SystemExit("Refusing to seed: " + "; ".join(problems))
    currency = currency.upper()
    scale = SCALES.get(currency, 1) if scale is None else scale
    timezone = timezone or ZONES.get(currency, "UTC")
    user_id = user_id or config.DEMO_USER_ID

    if reset:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
    from app.db import init_db
    from app.services import accounts, budgets, periods, prefs, recurring, summaries, transactions, users

    periods.freeze(today)               # "today" is the given day for the whole seeding
    keeper = None
    zone_token = None
    try:
        init_db()
        # One connection stays open while seeding: SQLite then keeps its write-ahead files instead of
        # deleting and recreating them each time a short connection closes (slow, especially on Windows).
        import sqlite3
        keeper = sqlite3.connect(path)
        keeper.execute("PRAGMA journal_mode=WAL")
        users.register_user(user_id)
        users.app_opened(user_id)
        prefs.set_prefs(user_id, currency, timezone=timezone)
        zone_token = periods.set_zone(timezone, user_id)   # in force for the whole run: no lookup on every call
        accounts.ensure_accounts(user_id)
        accounts.set_default_account(user_id, "card")

        rng = random.Random(rng_seed)
        start = start_date(today)
        items = make_items(today, start, rng)
        items.sort(key=lambda i: (i["day"], 0 if i["type"] == "income" else 1))
        round_limits = fit_budgets(items, today)

        def money(base):
            return amount_minor(base, scale)

        balances = {"cash": 0, "bank": 0, "card": 0, "mobile_money": 0}
        last_card_payment = None

        def move(day, from_account, to_account, minor, note):
            transactions.add_transfer(user_id, minor, from_account, to_account, note, day)
            balances[from_account] -= minor
            balances[to_account] += minor

        entry_ids = {}
        current_day = None
        for item in items:
            day = item["day"]
            if day != current_day:
                current_day = day
                # the card is paid off from the bank every Sunday
                if day.weekday() == 6 and balances["card"] < 0 and last_card_payment != day:
                    move(day, "bank", "card", -balances["card"], "Credit card payment")
                    last_card_payment = day
            minor = money(item["amount"])
            account = item["account"]
            if item["type"] == "expense":
                if account == "cash" and balances["cash"] < minor:
                    fifty = 50 * (scale if scale >= 5 else 1) * 100
                    need = minor - balances["cash"] + 0.6 * fifty          # leave some cash in the pocket
                    move(day, "bank", "cash", max(math.ceil(need / fifty) * int(fifty), int(2 * fifty)),
                         "ATM withdrawal")
                if account == "mobile_money" and balances["mobile_money"] < minor:
                    twenty = 20 * (scale if scale >= 5 else 1) * 100
                    need = minor - balances["mobile_money"] + 1.2 * twenty   # and some in the wallet
                    move(day, "bank", "mobile_money", max(math.ceil(need / twenty) * int(twenty), int(3 * twenty)),
                         "Wallet top-up")
                balances[account] -= minor
            else:
                balances[account] += minor
            entry, _ = transactions.add_entry(user_id, minor, item["type"], item["category"], account,
                                              item["note"], day)
            entry_ids.setdefault(item["note"], []).append(entry["id"])

        # --- budgets: set from this month's spending so the percentages hold on any run date -------
        month_start = periods.month_start()
        spent = {r["category"]: r["total_minor"] for r in summaries.by_category_minor(user_id, month_start)}
        targets = {"food": (0.70, 0.60, 0.80), "shopping": (0.95, 0.90, 0.99), "transport": (0.40, 0.33, 0.47)}
        limits = {}
        for category, (aim, low, high) in targets.items():
            if round_limits:                                # the tidy limits: 1,500 / 750 / 225 (times the scale)
                limit = amount_minor(BUDGET_LIMITS[category], scale) // 100
                limits[category] = limit
                budgets.set_limit(user_id, category, limit * 100)
                continue
            have = spent.get(category, 0)                   # too little spent so far this month: derive the limit
            unit = 10 ** max(0, int(math.floor(math.log10(max(have / 100 * 0.03, 1)))))
            limit = max(unit, round(have / 100 / aim / unit) * unit)
            while have / 100 / limit > high:
                limit += unit
            while have / 100 / limit < low and limit - unit > have / 100:
                limit -= unit
            limits[category] = limit
            budgets.set_limit(user_id, category, int(limit * 100))

        # --- the rules a real user would have set up --------------------------------------------------
        for note in ("Rent", "Monthly salary", "Netflix"):
            if entry_ids.get(note):
                recurring.create_from_entry(user_id, entry_ids[note][-1], "monthly")

        # --- what we made ---------------------------------------------------------------------------
        summary = {"currency": currency, "timezone": timezone, "scale": scale, "start": start.isoformat(),
                   "today": today.isoformat(), "entries": len(items), "balances": dict(balances), "months": {},
                   "limits": limits}
        for back in sorted({months_back(i["day"], today) for i in items}, reverse=True):
            first = today.replace(day=1)
            year, month = first.year, first.month - back
            while month < 1:
                month, year = month + 12, year - 1
            begin, end = date(year, month, 1), date(year, month, days_in(date(year, month, 1)))
            zone = periods.tz()
            income, expense = summaries.totals_minor(
                user_id, datetime(begin.year, begin.month, begin.day, tzinfo=zone),
                datetime(end.year, end.month, end.day, tzinfo=zone) + timedelta(days=1))
            summary["months"][f"{year}-{month:02d}"] = {
                "income": income / 100, "expenses": expense / 100,
                "savings_rate": round((income - expense) / income, 3) if income else None}
        overview = {b["category"]: b for b in budgets.overview(user_id)}
        summary["budget_percent"] = {c: overview[c]["percent"] for c in targets}
        return summary
    finally:
        periods.freeze(None)
        if zone_token is not None:
            periods._zone.reset(zone_token)
        if keeper is not None:
            keeper.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed demo/demo.db with believable demo data.")
    parser.add_argument("--currency", default="USD", help="USD (default), EUR, KES, GBP, ... (amounts scale to fit)")
    parser.add_argument("--seed", type=int, default=7, help="random seed: the same seed always gives the same data")
    parser.add_argument("--today", help="pretend today is YYYY-MM-DD (default: the real today)")
    parser.add_argument("--scale", type=float, help="multiply every amount (default: sensible for the currency)")
    parser.add_argument("--timezone", help="the demo user's timezone (default: one that fits the currency)")
    args = parser.parse_args(argv)
    if not config.DEMO_MODE:
        raise SystemExit("DEMO_MODE is off: set DEMO_MODE=true (or leave it unset) to seed the demo database")
    if os.path.abspath(config.DB_PATH) != os.path.abspath(config.DEMO_DB):
        raise SystemExit("Refusing to seed: the database is not demo/demo.db")
    today = date.fromisoformat(args.today) if args.today else date.today()
    summary = build(today, args.currency, args.seed, args.scale, args.timezone)
    print(f"Seeded {config.DB_PATH}")
    print(f"  {summary['entries']} entries from {summary['start']} to {summary['today']}, "
          f"{summary['currency']} ({summary['timezone']})")
    for month, row in summary["months"].items():
        rate = f"{row['savings_rate'] * 100:.0f}%" if row["savings_rate"] is not None else "-"
        print(f"  {month}: income {row['income']:,.0f}, expenses {row['expenses']:,.0f}, savings rate {rate}")
    print("  budgets used: " + ", ".join(f"{c} {p}%" for c, p in summary["budget_percent"].items()))
    print("  balances: " + ", ".join(f"{k} {v / 100:,.0f}" for k, v in summary["balances"].items()))


if __name__ == "__main__":
    main()
