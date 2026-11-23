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
| 📋 History | Your last 10 transactions (income marked +, expenses −), each with a 🗑️ Delete button |
| 📊 Summary | Income, expenses, net and savings rate (net ÷ income, shown when there is income) for this week (from Monday) or this month (from the 1st), plus spending by category |
| 💰 Budgets | Set a monthly limit per expense category. You're warned at 80% and when you go over |
| 🏦 Accounts | Balance per account (Cash, Bank, Card, Mobile Wallets) and your ⭐ default account, which new entries use without asking |
| ❓ Help | How the flow works |

- Expense categories: Food, Transport, Bills, Shopping, Fun, Other.
- Amounts accept `12.50`, `1,200` or `1 200`.
- Every step has a ❌ Cancel button (or send `/cancel`). Tapping any menu
  button also ends a half-finished entry and opens that screen, and an
  unfinished entry times out after 10 minutes.
- Every **Monday at 08:00** (`APP_TIMEZONE`, default Africa/Nairobi) each
  subscribed user who logged something gets a recap of the previous Monday–Sunday.
- Weeks start Monday 00:00 and months on the 1st at 00:00, both in `APP_TIMEZONE`.
  Summary, budgets and the recap all use the same periods.
- Admin: with `ADMIN_CHAT_ID` set, `/recap_now` sends the admin a preview of
  their own recap (nobody else receives anything).

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

## Cost
- Telegram Bot API: free
- Railway: free trial credit, then usage-based (a small worker like this
  typically runs a few dollars a month)
- No other external APIs, so there's no per-user or per-message cost.

## Notes
- The subscription check calls Telegram on every screen, so there's no way
  to fake being subscribed. Someone who leaves the channel is locked out again
  on their next tap.
