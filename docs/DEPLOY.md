# Deploying on Railway: step by step

The riskiest moment is the **first redeploy**. Right now the service has no
volume, so the database lives inside the container, and **any redeploy wipes
it**. Merging a pull request, attaching a volume or changing a variable can all
trigger one. So rescue the data **before anything else**, and follow these steps
in order.

You need: the Railway dashboard (or the Railway CLI), and Telegram on your phone.

---

## 1. Rescue the live data (before any redeploy)

1. Find your Telegram user id: message [@userinfobot](https://t.me/userinfobot); it
   replies with a number like `123456789`. Make sure you have pressed **Start** in
   your own bot, so it is allowed to message you.
2. Open a shell **in the running deployment**: Railway dashboard → your service →
   the active deployment → **⋯ → Shell**, or with the CLI: `railway ssh`.
3. Check whether there is anything to rescue:
   ```sh
   ls -la *.db data/ 2>/dev/null
   ```
   The original bot keeps its data in `finance_bot.db` (or in `data/finance_bot.db`
   if you already set `DB_PATH=/app/data/finance_bot.db` on a volume, in which case
   your data is already safe and you can skip to step 2 below).
4. Send the file to yourself through your own bot (replace `123456789` with your id):
   ```sh
   python -c "import os,httpx; r=httpx.post('https://api.telegram.org/bot'+os.environ['BOT_TOKEN']+'/sendDocument', data={'chat_id':'123456789','caption':'rescued finance_bot.db'}, files={'document':open('finance_bot.db','rb')}, timeout=60); print(r.status_code, r.text[:120])"
   ```
   `200` means it arrived. You'll see the file in your chat with the bot.
   Download it to your phone or computer too, as a second copy.

If the file is missing or tiny, or nobody has used the bot yet, there's nothing
to rescue. Carry on.

## 2. Add a volume

Service → **Settings → Volumes → New Volume**, mount path **`/data`**.
Railway then sets `RAILWAY_VOLUME_MOUNT_PATH=/data` for you, and the app keeps its
database at `/data/expenses.db`. Attaching the volume triggers a redeploy, which
is fine now that the data is rescued.

> If you earlier set `DB_PATH=/app/data/finance_bot.db`, either delete that variable
> (and move the volume to `/data`), or set `DB_PATH=/data/expenses.db`.

## 3. Generate a public domain

Service → **Settings → Networking → Generate Domain**. It comes with HTTPS, which
Telegram Mini Apps require. Railway exposes it as `RAILWAY_PUBLIC_DOMAIN`, and the
app uses it automatically (or set `PUBLIC_URL` yourself).

## 4. Set the variables

Service → **Variables**:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | already set |
| `WEBHOOK_SECRET` | 32+ random characters. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ADMIN_CHAT_ID` | your Telegram id from step 1, which gets backups, error alerts and admin commands |
Don't set `DB_PATH` (the volume default is right) or `PORT` (Railway sets it).
There is no currency or timezone variable: each user picks their own on /start.
If an older setup has `APP_TIMEZONE`, `DEFAULT_CURRENCY` or `DEFAULT_ACCOUNTS`,
they're ignored and can be deleted.

## 4b. The channel gate (later)

The gate has no variables: it lives in the database and starts **off**. The six
channels are already in the rotation (by numeric id). When you want it on:

1. In each channel: **Administrators → Add Admin →** your bot. No special rights are
   needed; Telegram only shows members (and lets a bot make invite links) for admins.
2. Send `/gate_list` from the admin account: every channel should show its title and
   **bot admin ✅**.
3. Send `/gate_on`. Any channel where the bot still isn't an admin (or that it can't
   see at all) is reported, and lets users through until it's fixed.

To change the rotation: forward a post from a channel to the bot and reply to it
with `/gate_add`; `/gate_remove n` takes one out. Each user needs channel 1 for
their first 30 days, then the next channel every 30 days, round the list. The
admin account is never checked. Old `GATE_ENABLED`, `GATE_CHANNELS`, `CHANNEL_ID`
/ `REQUIRED_CHANNEL` and `CHANNEL_LINK` / `CHANNEL_INVITE_LINK` variables are
ignored and can be deleted.

## 5. Health check and replicas

These come from `railway.json`: health check path `/healthz`, **1 replica**
(SQLite can't be shared between replicas), restart on failure, built from the
`Dockerfile`. Check that nothing in the dashboard overrides them.

## 6. Deploy

Check that Railway deploys `main`: service → **Settings → Source → Branch**. (A
service first connected to another branch, such as `muraja`, keeps deploying that
branch until this is changed.) Then merge the pull requests **in order** (#1 → #2
→ … → #6) into `main`. In **Deployments → Logs**, look for:

- `Database: /data/expenses.db (from RAILWAY_VOLUME_MOUNT_PATH)`
- `Bot started (webhook). Mini App: https://<your-domain>/`
- **no** line containing `WIPE`. If you see one, the volume isn't attached.

At startup the app registers the webhook and the **Open app** menu button.
Doing that again on every start is harmless.

## 7. Put the rescued data back

In your chat with the bot (from the `ADMIN_CHAT_ID` account), send the rescued
`finance_bot.db` file again, with the caption **`/restore`**. The bot:

1. checks the file is a real expense-bot database (if not: "Not restored", nothing changed),
2. saves the current database to `/data/backups/pre-restore-….db` first,
3. copies the file in and upgrades it (all migrations), then
4. replies with the counts: entries, users, budgets.

A daily backup `.db.gz` from the admin chat works the same way.

## 8. Check it

- In the bot: /start asks your currency, then your timezone (try 📍 Share my
  location). After that 📋 History shows your old entries and ➕ Add Expense works.
- The **Open app** button (bottom left of the chat) opens the Mini App.
- `/backup_now`: a `.db.gz` arrives in the admin chat.
- `/gate_status`: shows the gate off and the six channels (each with bot admin ✅ once added).
- `/recap_now`: a recap preview arrives.

Then do the **phone test** below.

---

## Optional: a staging bot

A second environment lets you try changes before users see them:
Railway → your project → **Environments → New Environment** (`staging`), with its
own volume and a **separate test bot** from @BotFather (its own `BOT_TOKEN`,
`WEBHOOK_SECRET` and domain). The cost is roughly one more small service.

## Cost

Expect about **$5–8 a month** at 1,000 users on the Hobby plan. Watch
**Usage** for the first week. If you regularly go over the included credit, the
same Docker image also runs on a small VPS.

## Restoring a backup later

- From Telegram: send the backup file (`.db` or `.db.gz`) with the caption `/restore` (admin only).
- From a shell on the server, with the bot stopped:
  `python -m app.services.backup restore <file.db or file.db.gz> [target]`.

---

## Phone test (light and dark)

Do this on a real phone, once in Telegram's light theme and once in dark.

- [ ] Open the bot, tap **Open app**: Home loads with this week's numbers.
- [ ] Week / Month toggle; quick add `200 food lunch`, then **Undo**.
- [ ] First start with a second Telegram account: pick a currency, then a timezone by location, list and typed city.
- [ ] Add an expense with the date set to yesterday, then a transfer Mobile Wallet → Cash.
- [ ] History: scroll, filter by Income, search a note, open an entry and edit it.
- [ ] Budgets: set a limit, add spending past 80%. The warning appears in the app **and** as a bot message.
- [ ] Accounts: rename one, make another the default.
- [ ] Settings: change the currency and the timezone, switch the monthly recap off, export the CSV (it arrives in the chat and opens in Excel or Sheets).
- [ ] In the bot: `500 food lunch` → Undo; History → Older → open an entry → Delete.
- [ ] The main button and the back button work, and the colours follow the theme.

## Final acceptance checklist

| Item | How it's checked |
|---|---|
| All nine Phase 1 bugs fixed, each with a test | Automated: `tests/test_nine_fixes.py` |
| Data survives a redeploy | Steps 2 + 6 above (log shows `/data/expenses.db`, no `WIPE`), then redeploy once and check History |
| A daily backup arrives in the admin chat; a restore has been tried once | Automated: `tests/test_scale.py`, `tests/test_restore.py`. On Railway: wait for 03:00 UTC, or `/backup_now`, then step 7 |
| The weekly recap arrives Monday 08:00 in each user's own timezone | Automated: `tests/test_worldwide.py` (Tokyo and New York users), `tests/test_better_recaps.py`. On Railway: `/recap_now`, then wait for Monday |
| Every user picks their currency and timezone at first start | Automated: `tests/test_worldwide.py`. Phone test |
| All bot text is in one file | Automated: `tests/test_strings.py` |
| Channel gate: in the database by numeric id, off until /gate_on, rotation every 30 days per user, every member status, admin exempt, never mid-entry | Automated: `tests/test_gate.py`. On Railway: `/gate_list` |
| The Mini App opens from the menu button and works in light and dark themes | Phone test |
| Entries match between the bot and the Mini App | Automated: `tests/test_api.py::test_entry_added_in_the_app_shows_in_bot_history_and_back`. Phone test |
| Quick entry, editing, past dates and transfers work in both | Automated: `tests/test_quick_entry.py`, `test_edit_entries.py`, `test_past_dates.py`, `test_transfers.py`. Phone test |
| The README matches what the app does | Automated: every command in the README must exist (`tests/test_nine_fixes.py::test_3…`) |
