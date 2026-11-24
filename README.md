# Personal Finance Bot + Mini App

Track spending and income in Telegram: a **bot** for quick logging, and a
**Mini App** (a web app that opens inside Telegram) with charts, filters and
editing. Both share one database and one set of rules, so they never disagree.
An optional [channel gate](#the-channel-gate) can ask users to be in one of your
channels each month, rotating through a list. It works **anywhere in the world**: each
user picks their own currency and timezone the first time they start the bot.
It runs as **one service on Railway**.

- [What it does](#what-it-does) · [The bot](#the-bot) · [The Mini App](#the-mini-app) · [The channel gate](#the-channel-gate)
- [Configuration](#configuration) · [Local development](#local-development) · [Deploying](#deploying)
- [How it works](#how-it-works) · [Backups and restore](#backups-and-restore) · [Tests](#tests)

## What it does

- Log expenses, income and transfers between accounts, for today or any past date.
- One-line **quick entry**: `500 food lunch`, `+20000 salary`, `350 transport wallet taxi`.
- **Budgets** per category, with a warning at 80% and when you go over.
- **Accounts** you name yourself (new users start with Cash, Bank, Card and Mobile Wallet), with balances and a default.
- **Categories** you can add, rename and hide.
- **Recurring** entries (rent, salary, subscriptions), logged automatically each week or month.
- A **weekly recap** every Monday and a **monthly recap** on the 1st, at 08:00 the user's own time, compared with the period before.
- **CSV export** that opens in Excel and Google Sheets.
- Your own **currency** (shown like `USD 1,500`) and **timezone**, so weeks, months and budgets follow your clock.
- Every bot message lives in one file, `app/strings.py`, ready for translation.

## The bot

### First start

A new user answers two questions before anything else:

1. **Currency:** a button per common currency (USD, EUR, GBP, INR, NGN, KES…), or ✏️ Other to type any 3-letter code.
2. **Timezone:** 📍 Share my location, pick a region and then a city, or type a city (`London`, `Lagos`) or an
   offset (`UTC+3`). The location is looked up offline; nothing is sent anywhere.

Then the menu appears, with four accounts (Cash, Bank, Card, Mobile Wallet) to rename or add to.
Both answers can be changed any time in ⚙️ Settings. Users from before this change are asked once, the next
time they write.

### Main menu

| Button | What happens |
| --- | --- |
| ➕ Add Expense | Amount → category → account (skipped when you have a ⭐ default; the confirmation then offers 🔁 Change account) → note, with a date choice: Today (default), Yesterday or 📅 Other date |
| 💵 Add Income | The same flow, with income categories |
| 📋 History | One message, 10 entries a page (income +, expenses −, transfers 🔁), with ⬅️ Newer / Older ➡️ and a filter: All, Expenses, Income or Transfers. Tap an entry's number to open it, then ✏️ Edit (amount, category, account, date, note, 🔁 Repeat) or 🗑️ Delete |
| 📊 Summary | This week (from Monday) or this month (from the 1st): income, expenses, net, savings rate, and spending by category |
| 💰 Budgets | Your monthly limits; set one per expense category |
| 🏦 Accounts | Balance per account and your ⭐ default. 🔁 Transfer moves money between accounts (it never counts as income or an expense). ➕ Add, ✏️ Rename and 🗄️ Archive accounts, and ♻️ restore archived ones. History and balances always stay |
| ⚙️ Settings | Currency (from a list, or any 3-letter code), 🕐 timezone, weekly and monthly recaps on/off, 🏷️ Categories (add, rename, hide or show again; a hidden category's past entries still count), 🔁 Recurring entries (stop any), 📤 Export CSV |
| ❓ Help | How the flow works |
| 📱 Open app | Opens the Mini App (shown once the service has an https address) |

Every step of a flow has ❌ Cancel. Tapping any menu button also ends a
half-finished entry and opens that screen, and an unfinished entry times out
after 10 minutes.

### Quick entry

Send a message that starts with an amount:

- `500 food lunch`: expense 500, Food, note "lunch"
- `+20000 salary`: a leading `+` means income
- `350 transport wallet taxi`: Transport, from the Mobile Wallet account, note "taxi"
- `500 food yesterday`: dated yesterday

Category and account words are matched case-insensitively. Your own names come
first, then built-in aliases such as lunch → Food, taxi → Transport and
wallet / momo / mpesa → Mobile Wallet. The rest becomes the note. With no category word you get
the category buttons, with the amount kept. Every quick entry has ↩️ Undo.

### Commands

- `/start`: the welcome (also shown after a new user's currency and timezone setup): a short message with an inline 📱 Open App button, then the main menu keyboard
- `/help`: how it works, with the full list of buttons
- `/cancel`: drop a half-finished entry
- `/settings`: the ⚙️ Settings screen
- `/export`: get your CSV now

The "/" menu in Telegram is filled in automatically at every start (`setMyCommands`):
the five commands above for everyone, and the admin commands too in the admin's own chat.
Descriptions are in `app/strings.py` (`cmd.*`).

**A nudge towards the Mini App:** people who log entries by hand in the chat get one
short tip with an 📱 Open the app button after their first entry, then after every
10th. Anyone who has opened the Mini App is never nudged, and nothing is sent when
the Mini App has no https address.

Admin only (the `ADMIN_CHAT_ID` account; anyone else gets no reply):

- `/recap_now`: a preview of your own weekly recap (`/recap_now month` for the monthly one)
- `/backup_now`: make a backup and send it to the admin chat
- `/gate_list`, `/gate_status`, `/gate_stats n`, `/gate_add`, `/gate_remove n`, `/gate_on`, `/gate_off`: manage the
  [channel gate](#the-channel-gate)
- **Restore:** send a `.db` or `.db.gz` file with the caption /restore (see [Backups and restore](#backups-and-restore))

### Messages the bot sends by itself

| When (in each user's own timezone) | What |
| --- | --- |
| Monday 08:00 | Weekly recap for the previous Monday–Sunday: income and expenses with ↑/↓ % vs the week before, net, savings rate, top category |
| The 1st, 08:00 | Monthly recap for the month that just ended, compared with the month before |
| Daily from 06:00 | Recurring entries that are due, each with ↩️ Undo |
| Daily 03:00 UTC | A database backup to the admin chat |
| When you add or edit an expense | A budget warning at 80% and when you go over, also for entries made in the Mini App |

An hourly job sends each recap once it is 08:00 (Monday, or the 1st) where the
user lives, within a 24-hour window, so a restart still delivers it. Each recap
can be switched off in Settings. Recaps are rate-limited and never sent twice,
even if the service restarts halfway.

## The Mini App

Opens from the bot's **menu button** or **📱 Open app**. There's no separate
login: Telegram's signed `initData` proves who you are, and the channel gate
applies here too, by the same rule.

| Screen | What you can do |
| --- | --- |
| Home | This week / this month: income, expenses, net, savings rate, spending by category, budget bars, account balances, and a quick-add box (with Undo) |
| History | Every entry grouped by day, loading more as you scroll. Filter by type, category, account and dates, and search notes. Tap an entry to edit or delete it |
| Add / Edit | Expense, income or transfer; amount, category, account (default preselected), date (today unless changed), note, and Repeat weekly or monthly |
| Budgets | Each category's limit and this month's progress; set or remove a limit |
| Income | This week / this month: total income and the change vs the period before ("+12% vs last month"), income by source with amounts and percentages, the period's income entries by day (tap to edit), and **+ Add income** |
| Settings → Accounts | Balances; add, rename, archive or restore; set the default; 🔁 transfer between accounts |
| Settings | 🏦 Accounts, currency, timezone (the phone's own is used on a first visit), both recaps, categories, recurring entries, and Export CSV (sent to your chat) |

It follows Telegram's light or dark theme and uses Telegram's main and back
buttons. Try it locally without Telegram: `python scripts/preview_app.py`.

## The channel gate

Users must be in one of your channels, a different one every 30 days. Everything is
kept in the database and managed by the admin (`ADMIN_CHAT_ID`) from the bot; there
are no environment variables for it.

- **Off** until you send `/gate_on`; `/gate_off` stops all checks again.
- **Channels** are stored by **numeric chat id only** (`-100…`), never by @username,
  so renaming a channel or the bot breaks nothing. Titles come from Telegram
  (`getChat`, kept a day).
- **The bot must be an administrator of every channel, with the "Invite users via
  link" right.** Telegram only shows a channel's members to its admins, and the
  bot makes the join links itself.
- **Invite links:** one per channel, named "Finance Bot", made with
  `createChatInviteLink` when the gate is turned on (`/gate_on`, or at startup while
  it's on), stored, and reused. A new one is made only if the old one was revoked.

### The schedule (one for everyone, automatic)

There is no free period, and every user, old or new, needs the same channel at the
same moment. The schedule is stored in the database: it started on **24 Nov 2026
00:00 (Nairobi time)** with **We Talk A Lot**. Period *n* = the number of whole
30-day blocks since the start; its channel is the one *n* places after the start
channel in the list, round again:

| Period | Dates (Nairobi) | Channel |
| --- | --- | --- |
| 0 | 24 Nov – 24 Dec 2026 | We Talk A Lot |
| 1 | 24 Dec 2026 – 23 Jan 2027 | Crypto Alpha Edge US |
| 2 | 23 Jan – 22 Feb 2027 | Hustle To Millions |
| 3 | 22 Feb – 24 Mar 2027 | Crypto Wall Street |
| 4 | 24 Mar – 23 Apr 2027 | Earn Stack |
| 5 | 23 Apr – 23 May 2027 | Crypto Notebook |
| 6 | 23 May – 22 Jun 2027 | We Talk A Lot again, and so on |

Nothing has to be changed by hand. Only the current period's channel is checked;
leaving a channel from an earlier period has no effect. A new user needs the
current channel from their first action. `/gate_schedule` shows the current and
next five periods with their dates.

### Staying in

- **Joined means** `creator`, `administrator` or `member`, or `restricted` while
  still a member.
- A "member" answer is cached for 15 minutes; a "not a member" answer is never
  cached; ✅ I've joined always asks Telegram again.
- **Checked only when a user starts something** (a menu screen, a command, the
  start of an entry, a quick entry, a Mini App screen), never in the middle of an
  entry. Nothing a user logged is ever touched.
- **Leaving the current channel:** the bot gets a `chat_member` update (the webhook
  asks Telegram for them), drops that user's cached answer at once, and their next
  action shows the "you left" message below.
- **What users see** (all in `app/strings.py`, under `gate.`) never explains how the
  gate works: no periods, days, schedule or other channels, only the current
  channel's name on the Join button.

  | When | Text |
  | --- | --- |
  | Bot join message | 👋 Welcome to Wallet Buddy! It's completely free. Just join our channel to get started. |
  | Mini App join screen | **🔓 One quick step** · Wallet Buddy is free to use. Join our community channel to unlock it. |
  | Buttons (both) | 📢 Join \<channel\> · ✅ I've joined |
  | Left the current channel | Looks like you left \<channel\>. Rejoin to keep using Wallet Buddy. Your data is safe. |
  | "I've joined" but not a member | We couldn't find you in the channel yet. Tap Join, then try again. |
  | Joined | ✅ You're in! Welcome to Wallet Buddy. |

  Without the invite right in a channel there is no Join button, and the admin
  gets an alert. The schedule and days left appear only in the admin commands.
- **If Telegram can't answer**, the last known answer is used, and a user is never
  blocked just because of an error. If the bot can't check a channel at all (not an
  admin, or can't see it), users are let through and the admin is alerted.
- **The Mini App** follows the same rule: a 403 carrying the join screen's texts and
  link (from the strings file), which the app shows as they are.
- **The admin** is never checked.

### Counting the members the bot brings in

Every step is recorded in `gate_events` with the global period number, only for the
channel that was required at that moment:

| Event | When |
| --- | --- |
| `shown` | the join screen was displayed |
| `already_member` | a member the first time they were checked this period |
| `joined_via_bot` | not a member when first checked this period, a member afterwards |
| `left` | left their current required channel |
| `rejoined` | joined again after leaving, in the same period |

### Admin commands

| Command | What it does |
| --- | --- |
| `/gate_on` / `/gate_off` | Start or stop checking. `/gate_on` also checks every channel (admin, invite right), makes the invite links, and reports anything that fails |
| `/gate_list` | The current channel, the period's start and end, days left and the next channel; then the list: order, title, id, bot admin ✅/❌, invite link ✅/❌ |
| `/gate_schedule` | The current period and the next five, with their dates |
| `/gate_status` | The current period (channel, dates, days left, next channel), then per channel: users required to be in it now, shown, joined via bot, already members, left, rejoined, still subscribed now |
| `/gate_stats n` | The same numbers for the last *n* days |
| `/gate_add` | Forward any post from the channel to the bot, then reply to it with `/gate_add`. The bot reads the id, checks it's an admin there, and adds it to the end (up to 6). `/gate_add -100…` works too |
| `/gate_remove n` | Takes channel *n* out; the ones after it move up |

## Configuration

Set these on Railway (Variables) or, locally, in a `.env` file (see
`.env.example`). Real environment variables always win over `.env`.

| Variable | Required | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from @BotFather |
| `WEBHOOK_SECRET` | in production | 32+ random characters; Telegram sends it with every update |
| `PUBLIC_URL` | for the Mini App | Base https URL. Default: `https://$RAILWAY_PUBLIC_DOMAIN` |
| `ADMIN_CHAT_ID` | no | Your Telegram id: backups, error alerts, admin commands |
| `DB_PATH` | no | Database file. Default: `$RAILWAY_VOLUME_MOUNT_PATH/expenses.db`, else an existing `./finance_bot.db`, else `./data/expenses.db` |
| `USE_POLLING` | no | `true` for local development (no webhook needed) |
| `PORT` | no | Set by Railway (default 8000) |

## Local development

```bash
python -m venv venv
source venv/bin/activate             # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # fill in BOT_TOKEN (the channel gate is off until /gate_on)
echo USE_POLLING=true >> .env        # no webhook or public URL needed locally
python -m app.main                   # the bot, plus the API and Mini App on http://localhost:8000
pytest                               # the tests
python scripts/preview_app.py        # the Mini App with demo data and a fake Telegram
python scripts/load_test.py          # 1,000 simulated users (about 2 minutes)
```

Use a separate **test bot** from @BotFather for local work, not the live one.

## Deploying

**Follow [docs/DEPLOY.md](docs/DEPLOY.md).** It covers rescuing the current data
before the first redeploy, the volume, the domain, the variables, putting the
data back with /restore, a phone test, and the final checklist.

Railway settings live in `railway.json`: built from the `Dockerfile`, health
check `/healthz`, exactly **one replica**, restart on failure. The same Docker
image runs on any VPS.

## How it works

```
app/
  main.py         builds the bot (handlers, jobs) and starts the web server
  config.py       every environment variable (and .env for local development)
  strings.py      every message users see, keyed for translation: t("menu.add")
  db.py           SQLite connections, WAL settings, numbered migrations
  migrations/     001_initial.sql ... 010_user_timezone.sql, applied in order, once
  services/       all the rules: entries, budgets, accounts, categories, periods,
                  timezones, summaries, quick entry, recurring, recaps, backups, export
  bot/            Telegram handlers, keyboards, conversations, membership check,
                  first-start setup (onboarding.py)
  web/            FastAPI: initData auth, JSON API, webhook, /healthz, the Mini App files
scripts/          preview_app.py, load_test.py
tests/            pytest, driving the real handlers against a fake Telegram
```

- **One process:** uvicorn serves FastAPI on `$PORT`: the JSON API at `/api/*`,
  the Telegram webhook at `/telegram/webhook` (checked against
  `WEBHOOK_SECRET`), `/healthz`, and the Mini App at `/`. The bot runs in the same
  event loop. Without `WEBHOOK_SECRET` or an https address it falls back to
  polling, with a warning.
- **One set of rules:** the bot handlers and the API both call `app/services/`.
- **Each user's own clock:** there is no app-wide timezone or currency. The
  timezone in force is a context variable, set for the user behind each bot
  update and each API request; service functions that take a `user_id` switch to
  that user's zone themselves (`@in_user_zone`), so jobs get it right too. Server
  jobs such as the backup run on UTC.
- **Translating:** every message is `t("key", value=...)` from `app/strings.py`.
  Copy the `EN` table, translate the values (keep the `{placeholders}`) and add it
  to `LANGUAGES`; `tests/test_strings.py` checks the keys and placeholders match.
  The Mini App's own labels are still in `app/web/static/app.js`.
- **Money** is stored as whole cents (`amount_minor`), so totals are exact.
  Entries keep two dates: when the money moved (`occurred_at`, used everywhere)
  and when it was logged (`created_at`).
- **Migrations** are numbered SQL files, applied in order and recorded in
  `schema_version`. They only add; nothing is dropped or rewritten. Before the
  first pending migration runs on a database with data, an untouched copy is
  saved to `backups/pre-migration-*.db`.
- **Exactly one replica:** SQLite is a single file on one volume and can't be
  shared between replicas. It's comfortable to about 10,000 active users; past
  that, move to Postgres.
- **At about 1,000 users:** membership checks are cached for 15 minutes (only a
  "member" answer is cached, and ✅ I've joined always checks live). Only
  sending calls are rate-limited, and the recap sends at most 25 messages a
  second. Users who block the bot are skipped until they write again. SQLite
  runs in WAL mode with a 5-second busy timeout, and database work never blocks
  the event loop.
- **Mini App files** are sent with `Cache-Control: no-cache`, so a deploy is never
  hidden behind a stale cached copy.

## Backups and restore

- **Every day at 03:00 UTC** the app writes `backups/expenses-YYYY-MM-DD.db` next to
  the database, using SQLite's backup API (safe while running). It keeps 7 daily
  and 4 weekly copies, and also sends a gzipped copy to `ADMIN_CHAT_ID`.
  `/backup_now` does the same at any time.
- **Restore from Telegram (admin):** send the `.db` or `.db.gz` file to the bot
  with the caption /restore. It checks the file, saves the current database
  first (`backups/pre-restore-*.db`), copies the file in, upgrades it with the
  migrations, and replies with the counts. A bad file changes nothing.
- **Restore on the server** (bot stopped):
  `python -m app.services.backup restore <file.db|file.db.gz> [target]`.

## Tests

`pytest` runs about 560 tests (about 310 of them check the strings file) in
roughly 2 minutes. They drive the real
handlers and API against a fake Telegram, and reject any message that isn't
valid Telegram HTML. They cover the 9 original bug fixes, the first-start setup
(currency, timezone by button, city, offset or location), weeks, months, budgets,
recaps and recurring entries in different users' timezones, quick entry, budget thresholds at 80% and 100%, initData validation,
one user trying to reach another's entries, every API endpoint, migrations from
the very first schema with no data lost, backup and restore, recaps, recurring
entries, transfers and the CSV export.

## Cost

The Telegram Bot API is free. On Railway's Hobby plan, expect about $5–8 a month
at 1,000 users. No other paid APIs are used.
