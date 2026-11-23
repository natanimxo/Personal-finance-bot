# Personal Finance Telegram Bot

Track spending and income right inside Telegram. Users must be subscribed to
your channel to use the bot — they're checked on every screen via Telegram's
`getChatMember` API, so it can't be faked by leaving after joining.

## What it does
Everything works through buttons — there are no commands to type besides
`/start`, `/help` and `/cancel`.

| Button | What happens |
| --- | --- |
| ➕ Add Expense | Type the amount → pick a category → pick an account (skipped when you have a ⭐ default; the confirmation then offers 🔁 Change account) → add a note or skip |
| 💵 Add Income | Same flow, with income categories (Salary, Freelance, Business, Gift, Other) |
| 📋 History | Your last 10 transactions (income marked +, expenses −), each with ✏️ Edit (amount, category, account, note) and 🗑️ Delete |
| 📊 Summary | Income, expenses, net and savings rate (net ÷ income, shown when there is income) for this week (from Monday) or this month (from the 1st), plus spending by category |
| 💰 Budgets | Set a monthly limit per expense category. You're warned at 80% and when you go over |
| 🏦 Accounts | Balance per account (Cash, Bank, Card, Mobile Wallets) and your ⭐ default account, which new entries use without asking |
| ❓ Help | How the flow works |

- **Quick entry:** just send `500 food lunch`, `+20000 salary` or
  `350 transport mpesa matatu`. The number comes first, and `+` means income.
  Category and account words are matched case-insensitively (aliases like
  lunch → Food, matatu → Transport, mpesa → Mobile Wallets), and the rest
  becomes the note. With no category word you get the category buttons, with
  the amount kept. Every quick entry has an ↩️ Undo button. The Mini App's
  Home screen has the same box.
- Expense categories: Food, Transport, Bills, Shopping, Fun, Other.
- Amounts accept `12.50`, `1,200` or `1 200`.
- Every step has a ❌ Cancel button (or send `/cancel`). Tapping any menu
  button also ends a half-finished entry and opens that screen, and an
  unfinished entry times out after 10 minutes.
- Every **Monday at 08:00** (`APP_TIMEZONE`, default Africa/Nairobi) each
  subscribed user who logged something gets a recap of the previous Monday–Sunday.
- Weeks start Monday 00:00 and months on the 1st at 00:00, both in `APP_TIMEZONE`.
  Summary, budgets and the recap all use the same periods.
- Admin commands (only for `ADMIN_CHAT_ID`; anyone else gets no reply):
  `/recap_now` sends the admin a preview of their own recap, and
  `/backup_now` makes a backup and sends it to the admin chat.
- Errors are logged in full, and the admin gets a short alert (at most one a minute).
- `GET /healthz` on `$PORT` answers 200 when the database responds, 503 when it doesn't.

## 📱 The Mini App
A web app that opens inside Telegram from the bot's **menu button** or the
**📱 Open app** button in the main menu. It does everything the bot does, plus:
- **Home:** this week or this month, with income, expenses, net, savings rate,
  spending by category, budget bars and account balances.
- **History:** every entry grouped by day, with infinite scroll, filters (type,
  category, account, dates) and note search. Tap an entry to edit or delete it.
- **Add / Edit:** amount, expense or income, category, account (your default
  is preselected) and note.
- **Budgets, Accounts and Settings:** set or remove limits, set the default
  account, and change your currency and the weekly recap switch.

There's no separate login: the app proves who you are with Telegram's signed
`initData`, and the channel requirement applies there too. The bot and the app
share one database and one set of rules (`app/services/`), so an entry added
in either shows in both, and a budget warning from the app also arrives as a
bot message.

Try it locally without Telegram: `python scripts/preview_app.py`, then open the
printed URL. It uses demo data and a fake Telegram.

## 1. Create the bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, follow the prompts.
2. Copy the token it gives you — that's `BOT_TOKEN`.

## 2. Set up the subscription gate
1. `CHANNEL_ID` = your channel's `@username` (must be public), or its numeric
   chat ID if private (get this by forwarding a message from the channel to
   [@JsonDumpBot](https://t.me/JsonDumpBot) or similar).
2. **Add your bot as an admin of the channel** — this is required, otherwise
   `getChatMember` calls will fail and the bot will refuse everyone.
3. `CHANNEL_LINK` = the public `t.me/...` link people tap to join.

## 3. Environment variables
| Variable | Required | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from BotFather |
| `CHANNEL_ID` | yes | `@username` or numeric ID of the channel users must join (old name `REQUIRED_CHANNEL` still works) |
| `CHANNEL_LINK` | yes | Link shown on the "join the channel" screen (old name `CHANNEL_INVITE_LINK` still works) |
| `APP_TIMEZONE` | no | Timezone for weeks, months and the recap (default `Africa/Nairobi`) |
| `ADMIN_CHAT_ID` | no | Telegram id allowed to use `/recap_now` |
| `PUBLIC_URL` | for the Mini App | Base https URL. Default: `https://$RAILWAY_PUBLIC_DOMAIN` |
| `WEBHOOK_SECRET` | for webhook mode | 32+ random characters; Telegram sends it with every update |
| `USE_POLLING` | no | `true` for local development (no webhook) |
| `DB_PATH` | no | Where the SQLite database lives. Default: `$RAILWAY_VOLUME_MOUNT_PATH/expenses.db`, else an existing `./finance_bot.db`, else `./data/expenses.db` |

`.env.example` lists every variable, including the ones later phases use.

## 4. Run locally (optional, to test first)
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env           # then fill in your real values
export $(cat .env | xargs)    # Windows PowerShell: set each one with $env:BOT_TOKEN="..."
python -m app.main
pytest                        # run the tests
```
`.env` and `finance_bot.db` are in `.gitignore` — never commit your real token.

## 5. Deploy on Railway
1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → pick this repo
   (the default branch is `main`).
2. Railway builds the `Dockerfile` and runs `python -m app.main`.
3. In your service's **Variables** tab add `BOT_TOKEN`, `CHANNEL_ID` and `CHANNEL_LINK` (a service that already has `REQUIRED_CHANNEL` and `CHANNEL_INVITE_LINK` keeps working).
4. **Important — persistent storage:** Railway's filesystem resets on every
   redeploy, which would wipe the SQLite database. Go to **Settings → Volumes →
   New Volume**, mount it at `/app/data`, and add the variable
   `DB_PATH=/app/data/finance_bot.db`. No code change is needed.
5. Deploy. Check **Deployments → Logs** for `Bot starting...` to confirm it's live.

## How it runs
One process: uvicorn serves FastAPI (`app/web/server.py`) on `$PORT` with the
JSON API at `/api/*`, the Telegram webhook at `/telegram/webhook`, `/healthz`,
and the Mini App's files at `/`. The bot runs in the same event loop.
- **Webhook mode** (production) needs `WEBHOOK_SECRET` and an https `PUBLIC_URL`.
  At startup the app registers the webhook and the menu button; doing that
  again on every start is harmless.
- **Polling mode**: with `USE_POLLING=true`, or automatically (with a warning
  in the logs) while `WEBHOOK_SECRET` or a public https URL is missing. An
  existing deployment therefore keeps working before those are set. The Mini
  App needs the https URL.
- Amounts are stored as whole cents (`amount_minor`). The old `amount` column
  is still written, and every start logs whether the two agree.

## Backups and restore
- Every day at **03:00** (`APP_TIMEZONE`) the bot writes
  `backups/expenses-YYYY-MM-DD.db` next to the database, using SQLite's backup
  API (safe while the bot is running). It keeps the newest 7 daily copies plus
  one copy for each of the 4 weeks before them.
- A gzipped copy is also sent to `ADMIN_CHAT_ID`, so a backup exists off the
  server. `/backup_now` does the same on demand.
- Before any database migration runs, a `backups/pre-migration-*.db` copy is
  written first. These are never deleted automatically.

**To restore** (stop the bot first, so nothing writes while the file is replaced):
1. Get the backup: a `backups/expenses-YYYY-MM-DD.db` file, or the `.db.gz` from the admin chat.
2. Run `python -m app.services.backup restore <backup file> [target]`. It
   unzips if needed, removes stale `-wal`/`-shm` files, writes the file to
   `DB_PATH` (or `target`), and checks it is an expense-bot database.
   On Railway, use the service's shell, or upload the file to the volume.
3. Start the bot. Its migrations bring an older backup up to the current schema.

## Running at about 1,000 users
- Membership checks are cached for 15 minutes per member. A "not a member"
  answer is never cached, and "✅ I've subscribed" always checks live. If
  Telegram's check fails, the last known answer is used, so a Telegram hiccup
  doesn't lock members out.
- Only calls that send messages are rate-limited (Telegram allows about 30 a
  second); the recap sends at most 25 a second. Each user's last recap week is
  stored, so a restart in the middle of a recap never sends anyone a duplicate.
- A user who blocks the bot is marked inactive and skipped; they become active
  again the next time they write to it.
- SQLite runs in WAL mode with a 5 s busy timeout, and every database call runs
  off the event loop. `python scripts/load_test.py` checks all of this with
  1,000 simulated users (about 2 minutes, temporary database only).
- Run exactly **one** replica: SQLite can't be shared between replicas.

## Cost
- Telegram Bot API: free
- Railway: free trial credit, then usage-based (a small worker like this
  typically runs a few dollars a month)
- No other external APIs, so there's no per-user or per-message cost.

## Notes
- The subscription check calls Telegram on every screen, so there's no way
  to fake being subscribed. Someone who leaves the channel is locked out again
  on their next tap.
