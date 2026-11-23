# Personal Finance Bot + Mini App

Track spending and income in Telegram: a **bot** for quick logging, and a
**Mini App** (a web app that opens inside Telegram) with charts, filters and
editing. Both share one database and one set of rules, so they never disagree.
Users must be members of your channel. It runs as **one service on Railway**.

- [What it does](#what-it-does) · [The bot](#the-bot) · [The Mini App](#the-mini-app)
- [Configuration](#configuration) · [Local development](#local-development) · [Deploying](#deploying)
- [How it works](#how-it-works) · [Backups and restore](#backups-and-restore) · [Tests](#tests)

## What it does

- Log expenses, income and transfers between accounts, for today or any past date.
- One-line **quick entry**: `500 food lunch`, `+20000 salary`, `350 transport mpesa matatu`.
- **Budgets** per category, with a warning at 80% and when you go over.
- **Accounts** you name yourself (Cash, M-Pesa, Bank…), with balances and a default.
- **Categories** you can add, rename and hide.
- **Recurring** entries (rent, salary, subscriptions), logged automatically each week or month.
- A **weekly recap** every Monday and a **monthly recap** on the 1st, compared with the period before.
- **CSV export** that opens in Excel and Google Sheets.
- Your own **currency**, shown like `KES 1,500`.

## The bot

### Main menu

| Button | What happens |
| --- | --- |
| ➕ Add Expense | Amount → category → account (skipped when you have a ⭐ default; the confirmation then offers 🔁 Change account) → note, with a date choice: Today (default), Yesterday or 📅 Other date |
| 💵 Add Income | The same flow, with income categories |
| 📋 History | One message, 10 entries a page (income +, expenses −, transfers 🔁), with ⬅️ Newer / Older ➡️ and a filter: All, Expenses, Income or Transfers. Tap an entry's number to open it, then ✏️ Edit (amount, category, account, date, note, 🔁 Repeat) or 🗑️ Delete |
| 📊 Summary | This week (from Monday) or this month (from the 1st): income, expenses, net, savings rate, and spending by category |
| 💰 Budgets | Your monthly limits; set one per expense category |
| 🏦 Accounts | Balance per account and your ⭐ default. 🔁 Transfer moves money between accounts (it never counts as income or an expense). ➕ Add, ✏️ Rename and 🗄️ Archive accounts, and ♻️ restore archived ones. History and balances always stay |
| ⚙️ Settings | Currency (from a list, or any 3-letter code), weekly and monthly recaps on/off, 🏷️ Categories (add, rename, hide or show again; a hidden category's past entries still count), 🔁 Recurring entries (stop any), 📤 Export CSV |
| ❓ Help | How the flow works |
| 📱 Open app | Opens the Mini App (shown once the service has an https address) |

Every step of a flow has ❌ Cancel. Tapping any menu button also ends a
half-finished entry and opens that screen, and an unfinished entry times out
after 10 minutes.

### Quick entry

Send a message that starts with an amount:

- `500 food lunch`: expense 500, Food, note "lunch"
- `+20000 salary`: a leading `+` means income
- `350 transport mpesa matatu`: Transport, from the M-Pesa account, note "matatu"
- `500 food yesterday`: dated yesterday

Category and account words are matched case-insensitively. Your own names come
first, then built-in aliases such as lunch → Food, matatu → Transport and
mpesa → mobile money. The rest becomes the note. With no category word you get
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
- **Restore:** send a `.db` or `.db.gz` file with the caption /restore (see [Backups and restore](#backups-and-restore))

### Messages the bot sends by itself

| When (in `APP_TIMEZONE`) | What |
| --- | --- |
| Monday 08:00 | Weekly recap for the previous Monday–Sunday: income and expenses with ↑/↓ % vs the week before, net, savings rate, top category |
| The 1st, 08:00 | Monthly recap for the month that just ended, compared with the month before |
| Daily 06:00 | Recurring entries that are due, each with ↩️ Undo |
| Daily 03:00 | A database backup to the admin chat |
| When you add or edit an expense | A budget warning at 80% and when you go over, also for entries made in the Mini App |

Each recap can be switched off in Settings. Recaps are rate-limited and never
sent twice, even if the service restarts halfway.

## The Mini App

Opens from the bot's **menu button** or **📱 Open app**. There's no separate
login: Telegram's signed `initData` proves who you are, and the channel
requirement applies here too.

| Screen | What you can do |
| --- | --- |
| Home | This week / this month: income, expenses, net, savings rate, spending by category, budget bars, account balances, and a quick-add box (with Undo) |
| History | Every entry grouped by day, loading more as you scroll. Filter by type, category, account and dates, and search notes. Tap an entry to edit or delete it |
| Add / Edit | Expense, income or transfer; amount, category, account (default preselected), date (today unless changed), note, and Repeat weekly or monthly |
| Budgets | Each category's limit and this month's progress; set or remove a limit |
| Accounts | Balances; add, rename, archive or restore; set the default |
| Settings | Currency, both recaps, categories, recurring entries, and Export CSV (sent to your chat) |

It follows Telegram's light or dark theme and uses Telegram's main and back
buttons. Try it locally without Telegram: `python scripts/preview_app.py`.

## Configuration

Set these on Railway (Variables) or, locally, in a `.env` file (see
`.env.example`). Real environment variables always win over `.env`.

| Variable | Required | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from @BotFather |
| `CHANNEL_ID` | yes | `@username` or numeric id of the channel users must join (old name `REQUIRED_CHANNEL` still works). **Add the bot as an admin of the channel**, or every check fails |
| `CHANNEL_LINK` | yes | The join link shown to non-members (old name `CHANNEL_INVITE_LINK` still works) |
| `WEBHOOK_SECRET` | in production | 32+ random characters; Telegram sends it with every update |
| `PUBLIC_URL` | for the Mini App | Base https URL. Default: `https://$RAILWAY_PUBLIC_DOMAIN` |
| `ADMIN_CHAT_ID` | no | Your Telegram id: backups, error alerts, admin commands |
| `APP_TIMEZONE` | no | For weeks, months, recaps and jobs (default `Africa/Nairobi`) |
| `DEFAULT_CURRENCY` | no | Currency for new users (default `KES`) |
| `DEFAULT_ACCOUNTS` | no | Accounts a new user starts with (default `Cash,M-Pesa,Bank,Card`; existing users keep their own) |
| `DB_PATH` | no | Database file. Default: `$RAILWAY_VOLUME_MOUNT_PATH/expenses.db`, else an existing `./finance_bot.db`, else `./data/expenses.db` |
| `USE_POLLING` | no | `true` for local development (no webhook needed) |
| `PORT` | no | Set by Railway (default 8000) |

## Local development

```bash
python -m venv venv
source venv/bin/activate             # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # fill in BOT_TOKEN, CHANNEL_ID, CHANNEL_LINK
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
  db.py           SQLite connections, WAL settings, numbered migrations
  migrations/     001_initial.sql ... 009_monthly_recap.sql, applied in order, once
  services/       all the rules: entries, budgets, accounts, categories, periods,
                  summaries, quick entry, recurring, recaps, backups, export
  bot/            Telegram handlers, keyboards, conversations, membership check
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
  "member" answer is cached, and ✅ I've subscribed always checks live). Only
  sending calls are rate-limited, and the recap sends at most 25 messages a
  second. Users who block the bot are skipped until they write again. SQLite
  runs in WAL mode with a 5-second busy timeout, and database work never blocks
  the event loop.
- **Mini App files** are sent with `Cache-Control: no-cache`, so a deploy is never
  hidden behind a stale cached copy.

## Backups and restore

- **Every day at 03:00** the app writes `backups/expenses-YYYY-MM-DD.db` next to
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

`pytest` runs about 240 tests in roughly 2½ minutes. They drive the real
handlers and API against a fake Telegram, and reject any message that isn't
valid Telegram HTML. They cover the 9 original bug fixes, periods and
timezones, quick entry, budget thresholds at 80% and 100%, initData validation,
one user trying to reach another's entries, every API endpoint, migrations from
the very first schema with no data lost, backup and restore, recaps, recurring
entries, transfers and the CSV export.

## Cost

The Telegram Bot API is free. On Railway's Hobby plan, expect about $5–8 a month
at 1,000 users. No other paid APIs are used.
