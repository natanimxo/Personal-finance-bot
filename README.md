# Personal Finance Telegram Bot

Track expenses right inside Telegram. Users must be subscribed to your channel
to use the bot — they're checked on every command via Telegram's
`getChatMember` API, so it can't be faked by leaving after joining.

## Commands
- `/add 12.50 food lunch` — log an expense
- `/list` — last 10 expenses
- `/delete 7` — delete expense #7
- `/summary` or `/summary month` — spending by category
- `/setbudget food 200` — set a budget, get warned when you go over
- `/budgets` — view budgets

## 1. Create the bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, follow the prompts.
2. Copy the token it gives you — that's `BOT_TOKEN`.

## 2. Set up the subscription gate
1. `REQUIRED_CHANNEL` = your channel's `@username` (must be public), or its numeric
   chat ID if private (get this by forwarding a message from the channel to
   [@JsonDumpBot](https://t.me/JsonDumpBot) or similar).
2. **Add your bot as an admin of the channel** — this is required, otherwise
   `getChatMember` calls will fail and the bot will refuse everyone.
3. `CHANNEL_INVITE_LINK` = the public `t.me/...` link people tap to join.

## 3. Run locally (optional, to test first)
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then fill in your real values
export $(cat .env | xargs)    # Windows: use a tool like python-dotenv instead
python bot.py
```

## 4. Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```
`.env` is in `.gitignore` — never commit your real token.

## 5. Deploy on Railway
1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → pick your repo.
2. Railway will detect the `Procfile` and run `python bot.py` as a worker.
3. Go to your service's **Variables** tab and add:
   - `BOT_TOKEN`
   - `REQUIRED_CHANNEL`
   - `CHANNEL_INVITE_LINK`
4. **Important — persistent storage:** Railway's filesystem resets on every
   redeploy, which will wipe your SQLite database (`finance_bot.db`).
   In your Railway service, go to **Settings → Volumes → New Volume**,
   mount it at `/app/data`, then change `DB_PATH` at the top of
   `database.py` to `"/app/data/finance_bot.db"` before deploying, so your
   users' data survives future deploys.
5. Deploy. Check the **Deployments → Logs** tab for `Bot starting...` to
   confirm it's live.

## Cost
- Telegram Bot API: free
- Railway: free trial credit, then usage-based (a small worker like this
  typically runs a few dollars a month)
- No other external APIs used, so there's no per-user or per-message cost.

## Notes
- The subscription check calls Telegram on every command, so there's no way
  for someone to fake being subscribed.
- If someone unsubscribes from the channel, they're locked out again
  automatically on their next command — no extra code needed.
