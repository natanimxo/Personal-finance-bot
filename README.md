# Personal Finance Bot + Mini App

Track spending and income in Telegram: a **bot** for quick logging, and a
**Mini App** (a web app that opens inside Telegram) with charts, filters and
editing. Both share one database and one set of rules, so they never disagree.
An optional [channel gate](#the-channel-gate) can ask users to join one of your
channels each month, after a free first month. It works **anywhere in the world**: each
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

- `/start`: the welcome message and menu
- `/help`: how it works
- `/cancel`: drop a half-finished entry
- `/settings`: the ⚙️ Settings screen
- `/export`: get your CSV now

Admin only (the `ADMIN_CHAT_ID` account; anyone else gets no reply):

- `/recap_now`: a preview of your own weekly recap (`/recap_now month` for the monthly one)
- `/backup_now`: make a backup and send it to the admin chat
- `/gate_status`: the channel gate: on or off, each channel and whether the bot is an admin there, and how many
  users are in their free month or on each channel
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
| Accounts | Balances; add, rename, archive or restore; set the default |
| Settings | Currency, timezone (the phone's own is used on a first visit), both recaps, categories, recurring entries, and Export CSV (sent to your chat) |

It follows Telegram's light or dark theme and uses Telegram's main and back
buttons. Try it locally without Telegram: `python scripts/preview_app.py`.

## The channel gate

Off unless `GATE_ENABLED=true`; while it's off, nobody is checked.

- **Channels:** `GATE_CHANNELS` lists up to 6, comma-separated, each as
  `@username|join link`, or `-100…numeric id|invite link` for a private channel.
  The id must be the `@username` or the numeric id, never an invite link. The older
  `CHANNEL_ID` + `CHANNEL_LINK` (or `REQUIRED_CHANNEL` + `CHANNEL_INVITE_LINK`) still
  work as a list of one.
- **Free first month:** each user's first 30 days, counted from their first contact
  with the bot (or, for users from before the gate, from their next message), need
  no channel.
- **Rotation, per user:** days 31–60 → channel 1, days 61–90 → channel 2, and so on,
  round the list again. A user only needs to be in the current month's channel.
- **Joined means** `creator`, `administrator` or `member`, or `restricted` while
  still a member.
- **When it's checked:** only when a user starts something (a menu screen, a
  command, the start of an entry, a quick entry, a Mini App screen), never in the
  middle of an entry. A "member" answer is cached for 15 minutes.
- **The join screen** names this month's channel, explains it changes monthly, and
  has 📢 Join and ✅ I've joined (which checks again at once).
- **The admin** (`ADMIN_CHAT_ID`) is never checked.
- **The bot must be an administrator of every channel** (no special rights needed):
  Telegram only shows a channel's members to its admins. At startup, with the gate
  on, the admin gets an alert for any channel where it isn't. Until it's fixed,
  that channel's check lets users through rather than locking everyone out.

## Configuration

Set these on Railway (Variables) or, locally, in a `.env` file (see
`.env.example`). Real environment variables always win over `.env`.

| Variable | Required | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from @BotFather |
| `GATE_ENABLED` | no | `true` turns on the [channel gate](#the-channel-gate). Default `false`: no channel checks |
| `GATE_CHANNELS` | with the gate | Up to 6 channels: `@username\|https://t.me/username,-1001234567890\|https://t.me/+invite`. **Add the bot as an admin of each** |
| `CHANNEL_ID` | no | One channel instead of `GATE_CHANNELS`: `@username` or numeric `-100…` id (old name `REQUIRED_CHANNEL` still works) |
| `CHANNEL_LINK` | no | Its join link (old name `CHANNEL_INVITE_LINK` still works) |
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
cp .env.example .env                 # fill in BOT_TOKEN (the channel gate is off by default)
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
