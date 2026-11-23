"""Phase 3: initData auth, the JSON API, the webhook and the Mini App files."""
import json
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_HISTORY
from app.db import get_conn, init_db
from app.services import transactions
from app.web.auth import InitDataError, make_init_data, sign, validate_init_data
from app.web.server import create_app
from tests.fake_telegram import UID, Harness

TOKEN = config.BOT_TOKEN
OTHER = 777


def auth(user_id=UID, **kw):
    return {"Authorization": "tma " + make_init_data({"id": user_id, "first_name": "Ann"}, TOKEN, **kw)}


@pytest.fixture
def server(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cret-" + "x" * 30)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://expenses.example.up.railway.app")
    harness = Harness()
    with TestClient(create_app(application=harness.app)) as client:
        client.harness = harness
        client.fake = harness.request
        yield client


# --- initData ---------------------------------------------------------------------
def test_valid_init_data_gives_the_user():
    user = validate_init_data(make_init_data({"id": 5, "first_name": "A"}, TOKEN), TOKEN)
    assert user["id"] == 5


def test_signature_matches_telegrams_algorithm():
    # Independent restatement of https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    import hashlib
    import hmac

    fields = {"auth_date": "1700000000", "query_id": "Q", "user": '{"id":1}'}
    check = "auth_date=1700000000\nquery_id=Q\nuser={\"id\":1}"
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    assert sign(fields, TOKEN) == hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def test_tampered_init_data_is_rejected():
    fields = dict(parse_qsl(make_init_data({"id": 5}, TOKEN)))
    fields["user"] = json.dumps({"id": 6})          # someone swaps in another user
    with pytest.raises(InitDataError):
        validate_init_data(urlencode(fields), TOKEN)


def test_init_data_signed_with_another_token_is_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data({"id": 5}, "999:other-bot"), TOKEN)


def test_expired_init_data_is_rejected():
    old = int(time.time()) - 24 * 3600 - 5
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(make_init_data({"id": 5}, TOKEN, auth_date=old), TOKEN)
    validate_init_data(make_init_data({"id": 5}, TOKEN, auth_date=int(time.time()) - 23 * 3600), TOKEN)


@pytest.mark.parametrize("header", ["", "tma ", "Bearer abc", "tma hash=abc&auth_date=1"])
def test_api_requires_valid_init_data(server, header):
    assert server.get("/api/me", headers={"Authorization": header}).status_code == 401


def test_expired_session_gets_401(server):
    old = int(time.time()) - 2 * 24 * 3600
    assert server.get("/api/me", headers=auth(auth_date=old)).status_code == 401


def test_user_id_from_the_client_is_ignored(server):
    r = server.post("/api/transactions", headers=auth(), json={"amount": "5", "category": "food", "user_id": OTHER})
    assert r.status_code == 201
    assert transactions.list_recent(OTHER) == [] and len(transactions.list_recent(UID)) == 1


def test_non_member_gets_403_with_the_join_link(server):
    server.fake.member_status = "left"
    r = server.get("/api/me", headers=auth())
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "not_subscribed", "join_link": config.CHANNEL_INVITE_LINK}


# --- API ------------------------------------------------------------------------
def test_me(server):
    body = server.get("/api/me", headers=auth()).json()
    assert body["user"]["id"] == UID
    assert body["settings"] == {"currency": "KES", "recap_enabled": True}
    assert [a["account"] for a in body["accounts"]] == ["cash", "bank", "card", "mobile_money"]
    assert body["default_account"] is None
    assert {c["key"] for c in body["categories"]["income"]} >= {"salary", "gift"}


def test_add_list_edit_delete(server):
    r = server.post("/api/transactions", headers=auth(), json={"amount": "1,500.50", "category": "food", "note": "lunch"})
    assert r.status_code == 201
    entry = r.json()["entry"]
    assert entry["amount_minor"] == 150050 and entry["account"] == "cash" and entry["created_at"].endswith("Z")

    r = server.patch(f"/api/transactions/{entry['id']}", headers=auth(), json={"amount": 20, "account": "bank", "note": "x"})
    assert r.status_code == 200 and r.json()["entry"]["amount_minor"] == 2000
    balances = {a["account"]: a["balance_minor"] for a in server.get("/api/accounts", headers=auth()).json()["accounts"]}
    assert balances["bank"] == -2000 and balances["cash"] == 0

    assert server.delete(f"/api/transactions/{entry['id']}", headers=auth()).status_code == 200
    assert server.get("/api/transactions", headers=auth()).json()["items"] == []
    assert server.delete(f"/api/transactions/{entry['id']}", headers=auth()).status_code == 404


def test_validation_errors_are_422_with_a_reason(server):
    for body, field in [({"amount": "12.345", "category": "food"}, "amount"),
                        ({"amount": "5", "category": "salary"}, "category"),
                        ({"amount": "5", "category": "food", "account": "crypto"}, "account"),
                        ({"amount": "5", "category": "food", "note": "x" * 201}, "note"),
                        ({"amount": "5", "type": "gift", "category": "food"}, "type")]:
        r = server.post("/api/transactions", headers=auth(), json=body)
        assert r.status_code == 422 and r.json()["field"] == field, body


def test_default_account_is_used_when_none_is_sent(server):
    server.put("/api/accounts", headers=auth(), json={"default_account": "mobile_money"})
    r = server.post("/api/transactions", headers=auth(), json={"amount": "5", "category": "food"})
    assert r.json()["entry"]["account"] == "mobile_money"


def test_paging_30_per_page_newest_first(server):
    for i in range(65):
        transactions.add_expense(UID, i + 1, "food", f"n{i}")
    seen, cursor, pages = [], None, 0
    while True:
        r = server.get("/api/transactions", params={"cursor": cursor} if cursor else {}, headers=auth()).json()
        seen += [e["amount_minor"] for e in r["items"]]
        pages += 1
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert pages == 3 and len(seen) == 65
    assert seen == sorted(seen, reverse=True)


def test_filters_and_search(server):
    transactions.add_expense(UID, 10, "food", "Lunch at Java")
    transactions.add_expense(UID, 20, "transport", "matatu 100%", account="mobile_money")
    transactions.add_expense(UID, 500, "salary", "", type_="income", account="bank")
    get = lambda q: [e["amount_minor"] for e in server.get(f"/api/transactions?{q}", headers=auth()).json()["items"]]
    assert get("type=income") == [50000]
    assert get("category=transport") == [2000]
    assert get("account=bank") == [50000]
    assert get("q=java") == [1000]
    assert get("q=100%25") == [2000]           # % is matched literally
    assert get("q=_") == []                    # so is _
    from app.services import periods
    today = periods.now_local().date().isoformat()
    assert len(get(f"from={today}&to={today}")) == 3
    assert get("from=2020-01-01&to=2020-01-02") == []


def test_summary(server):
    server.post("/api/transactions", headers=auth(), json={"amount": "1000", "type": "income", "category": "salary"})
    server.post("/api/transactions", headers=auth(), json={"amount": "250", "category": "food"})
    s = server.get("/api/summary?period=month", headers=auth()).json()
    assert (s["income_minor"], s["expense_minor"], s["net_minor"], s["savings_rate"]) == (100000, 25000, 75000, 75)
    assert s["by_category"][0]["category"] == "food" and s["period"] == "month"
    assert {b["category"] for b in s["budgets"]} >= {"food", "bills"}
    assert server.get("/api/summary?period=year", headers=auth()).status_code == 422


def test_budget_warning_comes_back_and_is_also_sent_by_the_bot(server):
    server.put("/api/budgets", headers=auth(), json={"category": "food", "limit": "100"})
    server.fake.sent.clear()
    r = server.post("/api/transactions", headers=auth(), json={"amount": "85", "category": "food"})
    assert r.json()["warning"]["level"] == "near" and r.json()["warning"]["percent"] == 85
    bot_messages = [p for e, p in server.fake.sent if e == "sendMessage"]
    assert len(bot_messages) == 1 and bot_messages[0]["chat_id"] == UID and "85%" in bot_messages[0]["text"]

    r = server.post("/api/transactions", headers=auth(), json={"amount": "20", "category": "food"})
    assert r.json()["warning"]["level"] == "over"


def test_budgets_set_and_remove(server):
    b = server.put("/api/budgets", headers=auth(), json={"category": "food", "limit": "2,000"}).json()["budgets"]
    assert next(x for x in b if x["category"] == "food")["limit_minor"] == 200000
    b = server.put("/api/budgets", headers=auth(), json={"category": "food", "limit": None}).json()["budgets"]
    assert next(x for x in b if x["category"] == "food")["limit_minor"] is None
    assert server.put("/api/budgets", headers=auth(), json={"category": "salary", "limit": 5}).status_code == 422


def test_settings(server):
    r = server.put("/api/settings", headers=auth(), json={"currency": "etb", "recap_enabled": False})
    assert r.json()["settings"] == {"currency": "ETB", "recap_enabled": False}
    assert server.get("/api/me", headers=auth()).json()["settings"]["currency"] == "ETB"
    assert server.put("/api/settings", headers=auth(), json={"currency": "birr"}).status_code == 422


def test_recap_respects_the_off_switch(server):
    from app.services import prefs, users
    users.register_user(UID)
    users.register_user(OTHER)
    prefs.set_prefs(UID, recap_enabled=False)
    assert users.recap_candidates("2026-11-16") == [OTHER]


# --- isolation between users ----------------------------------------------------------
def test_one_user_cannot_read_or_change_another_users_entries(server):
    theirs = server.post("/api/transactions", headers=auth(OTHER), json={"amount": "99", "category": "food"}).json()["entry"]
    assert server.get("/api/transactions", headers=auth()).json()["items"] == []
    assert server.patch(f"/api/transactions/{theirs['id']}", headers=auth(), json={"amount": 1}).status_code == 404
    assert server.delete(f"/api/transactions/{theirs['id']}", headers=auth()).status_code == 404
    assert server.get("/api/summary", headers=auth()).json()["expense_minor"] == 0
    assert transactions.get_entry(OTHER, theirs["id"])["amount_minor"] == 9900


# --- bot <-> Mini App -----------------------------------------------------------------
def test_entry_added_in_the_app_shows_in_bot_history_and_back(server):
    server.post("/api/transactions", headers=auth(), json={"amount": "42", "category": "fun", "note": "from app"})
    webhook = {"X-Telegram-Bot-Api-Secret-Token": config.WEBHOOK_SECRET}

    def bot_says(text):
        server.fake.sent.clear()
        update = {"update_id": int(time.time() * 1000) % 10**9, "message": {
            "message_id": 1, "date": 0, "chat": {"id": UID, "type": "private"},
            "from": {"id": UID, "is_bot": False, "first_name": "Ann"}, "text": text}}
        assert server.post("/telegram/webhook", headers=webhook, json=update).status_code == 200
        for _ in range(100):  # the update is processed from the queue
            if server.fake.sent:
                time.sleep(0.05)
                break
            time.sleep(0.02)
        return [p.get("text", "") for _, p in server.fake.sent]

    history = bot_says(BTN_HISTORY)
    assert any("42.00" in t and "from app" in t for t in history)

    bot_says("➕ Add Expense")
    bot_says("17")
    server.fake.sent.clear()
    cb = {"update_id": 99, "callback_query": {"id": "c", "from": {"id": UID, "is_bot": False, "first_name": "Ann"},
          "chat_instance": "x", "data": "addcat_food", "message": {"message_id": 1, "date": 0,
          "chat": {"id": UID, "type": "private"}, "text": "x", "from": {"id": 1, "is_bot": True, "first_name": "B"}}}}
    for data in ("addcat_food", "addacc_card", "skip_note"):
        cb["update_id"] += 1
        cb["callback_query"]["data"] = data
        server.post("/telegram/webhook", headers=webhook, json=cb)
        time.sleep(0.3)
    items = server.get("/api/transactions", headers=auth()).json()["items"]
    assert [(e["amount_minor"], e["account"]) for e in items][:1] == [(1700, "card")]


# --- webhook, menu button, files, health ------------------------------------------------
def test_webhook_needs_the_secret(server):
    update = {"update_id": 1, "message": {"message_id": 1, "date": 0, "chat": {"id": UID, "type": "private"},
              "from": {"id": UID, "is_bot": False, "first_name": "A"}, "text": "/start"}}
    assert server.post("/telegram/webhook", json=update).status_code == 403
    assert server.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, json=update).status_code == 403


def test_startup_sets_webhook_and_menu_button(server):
    calls = dict(server.fake.calls)
    assert calls["setWebhook"]["url"] == "https://expenses.example.up.railway.app/telegram/webhook"
    assert calls["setWebhook"]["secret_token"] == config.WEBHOOK_SECRET
    menu = calls["setChatMenuButton"]["menu_button"]
    menu = json.loads(menu) if isinstance(menu, str) else menu
    assert menu["type"] == "web_app" and menu["web_app"]["url"] == "https://expenses.example.up.railway.app/"


def test_main_menu_has_open_app_button(server):
    from app.bot.keyboards import main_menu_keyboard
    buttons = [b for row in main_menu_keyboard().keyboard for b in row]
    assert any(b.text == "📱 Open app" and b.web_app.url.startswith("https://") for b in buttons)


def test_falls_back_to_polling_without_secret(monkeypatch):
    from app.web.server import delivery_mode
    monkeypatch.setattr(config, "USE_POLLING", False)
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://x.example")
    assert delivery_mode() == "polling"
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s")
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    assert delivery_mode() == "polling"
    monkeypatch.setattr(config, "PUBLIC_URL", "https://x.example")
    assert delivery_mode() == "webhook"


def test_mini_app_files_are_served(server):
    page = server.get("/")
    assert page.status_code == 200 and "telegram-web-app.js" in page.text
    assert server.get("/app.js").status_code == 200 and server.get("/styles.css").status_code == 200


def test_healthz(server, monkeypatch):
    assert server.get("/healthz").json() == {"ok": True, "db": "ok"}
    from app.web import health

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(health, "ping", broken)
    assert server.get("/healthz").status_code == 503


# --- amount_minor migration ------------------------------------------------------------------
def test_float_amounts_become_exact_cents(fresh_db):
    fresh_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(fresh_db)
    conn.executescript("""
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
        CREATE TABLE budgets (user_id INTEGER NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
            PRIMARY KEY (user_id, category));
        CREATE TABLE users (user_id INTEGER PRIMARY KEY);
        INSERT INTO expenses (user_id, amount, category, created_at) VALUES (1, 0.1, 'food', '2026-11-01T00:00:00'),
            (1, 0.2, 'food', '2026-11-01T00:00:00'), (1, 19.99, 'fun', '2026-11-01T00:00:00');
        INSERT INTO budgets VALUES (1, 'food', 150.5);
    """)
    conn.close()
    init_db()
    from app.db import check_amount_columns
    with get_conn() as c:
        assert [r[0] for r in c.execute("SELECT amount_minor FROM expenses ORDER BY id")] == [10, 20, 1999]
        assert c.execute("SELECT amount_minor FROM budgets").fetchone()[0] == 15050
    assert check_amount_columns()
    from app.services import summaries, periods
    from datetime import datetime, timezone
    income, expense = summaries.totals_minor(1, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert expense == 2029  # 0.1 + 0.2 + 19.99 exactly, no float drift


def test_list_is_ordered_by_date_not_by_id(server):
    """Entries logged out of order (past dates arrive in Phase 4) still list newest first, across pages."""
    ids = [transactions.add_expense(UID, n, "food") for n in range(1, 36)]
    with get_conn() as conn:  # give every entry a shuffled date
        for i, entry_id in enumerate(ids):
            conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?",
                         (f"2026-11-{(i * 7) % 28 + 1:02d}T10:00:00", entry_id))
    first = server.get("/api/transactions", headers=auth()).json()
    second = server.get("/api/transactions", params={"cursor": first["next_cursor"]}, headers=auth()).json()
    dates = [e["occurred_at"] for e in first["items"] + second["items"]]
    assert len(dates) == 35 and dates == sorted(dates, reverse=True)
    assert second["next_cursor"] is None
    assert server.get("/api/transactions", params={"cursor": "junk"}, headers=auth()).status_code == 422


def test_quick_add_in_the_app(server):
    r = server.post("/api/quick", headers=auth(), json={"text": "350 transport mpesa matatu"}).json()
    assert r["entry"]["amount_minor"] == 35000 and r["entry"]["account"] == "mobile_money"
    r = server.post("/api/quick", headers=auth(), json={"text": "500 sugar"}).json()
    assert r["entry"] is None and r["draft"]["amount_minor"] == 50000 and r["draft"]["note"] == "sugar"
    assert server.post("/api/quick", headers=auth(), json={"text": "hello"}).status_code == 422
