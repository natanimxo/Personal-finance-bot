# Promo screenshots and clips

Makes phone screenshots, vertical promo frames and short clips of the Mini App **without
touching production**: everything runs on your computer, on its own database
(`demo/demo.db`), as one demo user. No bot starts, nothing is sent to Telegram, and no real
data is read or written.

## One command

```powershell
pip install -r demo/requirements.txt
python -m playwright install ffmpeg      # once: the small video encoder
python demo/build.py
```

It seeds the demo data, starts the demo web app, takes the screenshots, builds the frames,
records the clips and zips everything to **`demo/promo-assets.zip`** (about 3–6 minutes; the
clips take most of it). It uses your installed Chrome or Edge; with neither, run
`python -m playwright install chromium` first.

Options (all optional):

| Flag | What it does |
| --- | --- |
| `--currency EUR` | Another currency: amounts scale to fit (`KES` is ×130, rounded to whole tens). Also `GBP`, `INR`, `NGN`, ... and the timezone follows (`Europe/Berlin` for EUR, `Africa/Nairobi` for KES) |
| `--scale 2` / `--timezone Asia/Tokyo` | Override the amount scale or the demo user's timezone |
| `--today 2026-11-28` | Pretend today is that date, in the data, the server and the browser. Every run then looks exactly the same, whenever you run it |
| `--seed 7` | The random seed. The same seed (and date) always gives the same data |
| `--themes light` | Only one theme |
| `--no-clips` | Skip the videos |

## What you get (`demo/output/`)

| Folder | Contents |
| --- | --- |
| `raw/<light or dark>/` | 1170×2532 PNGs (a 390×844 phone at 3×): `home_month`, `home_week`, `transactions`, `transactions_filtered`, `add_expense`, `budgets`, `income`, `settings` |
| `frames/<light or dark>/` | 1080×1920 vertical frames for Reels, TikTok and Shorts: a screenshot in a plain rounded phone on a gradient, with a headline: `home` "See where your money goes", `add` "Log expenses in seconds", `budgets` "Get warned before you overspend", `income` "Track every income source", `transactions` "Find any transaction instantly", `settings` "Any currency. Any timezone." |
| `clips/` | 5–10 second phone-sized `.webm` videos in both themes: `add_expense` (typing an expense and saving), `home_week_month` (switching the period), `budget_near_limit` (opening the budget at about 95%). A faint ring shows each tap |

The headlines are in `demo/frames.py` (`FRAMES`), the demo story in `demo/seed.py`.

## The demo data

One user, USD, about three months ending today: a 3,200 salary and 1,100 rent on the 1st,
a few freelance payments (250–600), one gift, coffee and lunches on weekdays, groceries and
dinners out at weekends, two subscriptions (Netflix, Spotify) and bills. Full months end with
a savings rate of about 18–25%. Budgets are set so Food is about 70% used, Shopping about 95%
(its bar turns amber) and Transport about 40%, on whatever day you run it. Accounts are Cash,
Bank, Card and Mobile Wallet with sensible balances (ATM withdrawals, wallet top-ups, the
card paid off weekly).

Early in a month the month view naturally has less spending than the savings-rate target
implies; for the most "encouraging" numbers run it in the second half of a month, or pin a
date such as `--today 2026-11-28`.

## Safety

- `DEMO_MODE=true` serves **only the web app**, on `127.0.0.1`, against `demo/demo.db`, never
  `DB_PATH`. `BOT_TOKEN`, `WEBHOOK_SECRET`, `PUBLIC_URL` and `ADMIN_CHAT_ID` are ignored.
- It **refuses to start** (with nothing touched) if any `RAILWAY_*` variable is set or
  `DB_PATH` points at `/data`.
- Telegram sign-in and the channel gate are skipped, and every request is the one demo user.
- The page loads `/demo-telegram.js` instead of Telegram's script: it fakes `Telegram.WebApp`
  and sets Telegram's default light and dark theme colours (`app/web/demo.py`).
- The add-expense clip saves one entry in the demo database and removes it again.
- `demo/demo.db` and `demo/output/` are in `.gitignore`; only the scripts are committed.

## Running the pieces by hand

```powershell
python demo/seed.py --today 2026-11-28          # (re)create demo/demo.db
$env:DEMO_MODE = "true"; python -m app.main     # http://127.0.0.1:8800/?theme=dark  (or ?theme=light)
python demo/screens.py                          # screenshots (starts its own server)
python demo/frames.py                           # frames, from the screenshots
python demo/clips.py                            # clips (starts its own server)
```
