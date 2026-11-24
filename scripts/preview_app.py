"""Run the Mini App locally with demo data and a fake Telegram (nothing real is contacted).

    python scripts/preview_app.py [port]

Prints a URL that opens the app signed in as a demo user. Outside Telegram the
app shows its own Save / Add button where Telegram would show the MainButton.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
work = Path(tempfile.mkdtemp(prefix="expense-preview-"))
os.environ.update(BOT_TOKEN="1:preview-token", CHANNEL_ID="@preview", CHANNEL_LINK="https://t.me/preview",
                  DB_PATH=str(work / "expenses.db"), WEBHOOK_SECRET="preview-secret",
                  PUBLIC_URL="https://preview.invalid", USE_POLLING="false")

import uvicorn  # noqa: E402

from app.db import get_conn, init_db  # noqa: E402
from app.services import accounts, budgets, transactions, users  # noqa: E402
from app.web.auth import make_init_data  # noqa: E402
from app.web.server import create_app  # noqa: E402
from tests.fake_telegram import UID, Harness  # noqa: E402

init_db()
users.register_user(UID)
accounts.set_default_account(UID, "mobile_money")
budgets.set_budget(UID, "food", 3000)
budgets.set_budget(UID, "transport", 1000)
demo = [  # (amount, category, type, account, note, days ago)
    (45000, "salary", "income", "bank", "November salary", 6), (1200, "food", "expense", "mobile_money", "Groceries <Naivas>", 0),
    (350, "transport", "expense", "mobile_money", "Matatu to town", 0), (2500, "bills", "expense", "bank", "KPLC tokens", 1),
    (800, "fun", "expense", "cash", "Movie night", 2), (650, "food", "expense", "cash", "Lunch", 2),
    (5000, "freelance", "income", "mobile_money", "Logo design", 3), (420, "transport", "expense", "mobile_money", "", 4),
    (3200, "shopping", "expense", "card", "Shoes", 5), (900, "food", "expense", "mobile_money", "Dinner", 9),
]
for amount, category, type_, account, note, days in demo:
    entry_id = transactions.add_expense(UID, amount, category, note, type_=type_, account=account)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET created_at = datetime('now', ?) WHERE id = ?", (f"-{days} days", entry_id))

init_data = make_init_data({"id": UID, "first_name": "Demo", "username": "demo"}, os.environ["BOT_TOKEN"])
from urllib.parse import quote  # noqa: E402
print(f"\nOpen: http://127.0.0.1:{PORT}/#tgWebAppData={quote(init_data)}\n", flush=True)
uvicorn.run(create_app(application=Harness().app), host="127.0.0.1", port=PORT, log_level="warning")
