"""Phase 4.3: past dates (occurred_at)."""
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import config
from app.bot.keyboards import BTN_ADD, BTN_CANCEL
from app.db import get_conn, init_db
from app.services import budgets, periods, summaries, transactions
from app.services.quick_entry import parse
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()


def last_month_day():
    return periods.month_start().date() - timedelta(days=3)


def test_old_rows_get_occurred_at_from_created_at(fresh_db):
    fresh_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(fresh_db)
    conn.executescript("""
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL);
        INSERT INTO expenses (user_id, amount, category, created_at) VALUES (1, 5, 'food', '2026-03-04T10:00:00');
    """)
    conn.close()
    init_db()
    with get_conn() as c:
        assert c.execute("SELECT occurred_at FROM expenses").fetchone()[0] == "2026-03-04T10:00:00"


def test_entry_dated_last_month_lands_in_last_months_summary(db):
    budgets.set_budget(UID, "food", 100)
    entry, warning = transactions.add_entry(UID, 9000, "expense", "food", "cash", "", last_month_day())
    assert warning is None                              # last month's spending doesn't warn about this month
    this_month = summaries.summary(UID, "month")
    assert this_month["expense_minor"] == 0
    assert budgets.month_total_for_category(UID, "food", periods.month_start()) == 0
    d = last_month_day()
    last_month = summaries.summary(UID, date_from=d.replace(day=1).isoformat(), date_to=d.isoformat())
    assert last_month["expense_minor"] == 9000
    assert periods.local_date_of(entry["occurred_at"]) == d


def test_logged_now_but_ordered_by_when_it_happened(db):
    old = transactions.add_entry(UID, 100, "expense", "food", "cash", "", periods.today() - timedelta(days=10))[0]
    new = transactions.add_entry(UID, 200, "expense", "food", "cash", "")[0]
    assert old["id"] < new["id"]
    earlier = transactions.add_entry(UID, 300, "expense", "food", "cash", "", periods.today() - timedelta(days=20))[0]
    assert [e["id"] for e in transactions.list_recent(UID)] == [new["id"], old["id"], earlier["id"]]


@pytest.mark.parametrize("day", [lambda: periods.today() + timedelta(days=1), lambda: "1999-12-31", lambda: "31/02"])
def test_bad_dates_are_refused(db, day):
    with pytest.raises(ValidationError):
        transactions.add_entry(UID, 100, "expense", "food", "cash", "", day())


def test_quick_entry_yesterday(db):
    assert parse("500 food yesterday lunch").day == periods.today() - timedelta(days=1)

    async def scenario():
        async with Harness() as h:
            out = await h.text("500 food yesterday")
            assert "📅" in out.texts[0]
            e = transactions.list_recent(UID)[0]
            assert periods.local_date_of(e["occurred_at"]) == periods.today() - timedelta(days=1)

    run(scenario())


# --- bot ----------------------------------------------------------------------------
def test_bot_today_by_default_yesterday_or_other_date(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("10")
            out = await h.tap("addcat_food")
            out = await h.tap("addacc_cash")
            assert "Date: <b>today</b>" in out.texts[-1]
            assert [b["text"] for b in out.buttons()][:3] == ["✓ Today", "Yesterday", "📅 Other date"]
            out = await h.tap("fdate:yesterday")
            assert "✓ Yesterday" in [b["text"] for b in out.buttons()]
            await h.tap("skip_note")
            assert periods.local_date_of(transactions.list_recent(UID)[0]["occurred_at"]) == periods.today() - timedelta(days=1)

            await h.text(BTN_ADD)
            await h.text("20")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            await h.tap("fdate:other")
            out = await h.text(f"{(periods.today() + timedelta(days=2)):%d/%m/%Y}")
            assert "future" in out.texts[0]
            d = last_month_day()
            out = await h.text(d.isoformat())
            assert f"{d:%a %d %b %Y}" in out.texts[-1]
            out = await h.text("old receipt")
            assert f"📅 {d:%a %d %b %Y}" in out.texts[-1]
            assert periods.local_date_of(transactions.list_recent(UID)[1]["occurred_at"]) == d

    run(scenario())


def test_cancel_while_typing_a_date(db):
    async def scenario():
        async with Harness() as h:
            await h.text(BTN_ADD)
            await h.text("10")
            await h.tap("addcat_food")
            await h.tap("addacc_cash")
            await h.tap("fdate:other")
            out = await h.text(BTN_CANCEL)
            assert "Cancelled" in out.texts[-1] and transactions.list_recent(UID) == []

    run(scenario())


def test_bot_edit_date(db):
    entry_id = transactions.add_expense(UID, 10, "food")

    async def scenario():
        async with Harness() as h:
            out = await h.tap(f"edit:{entry_id}")
            assert any(b["callback_data"] == f"eddate:{entry_id}" for b in out.buttons())
            await h.tap(f"edsetdate:{entry_id}:yesterday")
            assert periods.local_date_of(transactions.get_entry(UID, entry_id)["occurred_at"]) == periods.today() - timedelta(days=1)
            await h.tap(f"edf:date:{entry_id}")
            await h.text("2026-01-15")
            assert periods.local_date_of(transactions.get_entry(UID, entry_id)["occurred_at"]).isoformat() == "2026-01-15"

    run(scenario())


# --- API ----------------------------------------------------------------------------
def test_api_dates(fresh_db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    d = last_month_day().isoformat()
    with TestClient(create_app(application=Harness().app)) as client:
        e = client.post("/api/transactions", headers=headers, json={"amount": 5, "category": "food", "date": d}).json()["entry"]
        assert e["date"] == d
        future = (periods.today() + timedelta(days=1)).isoformat()
        r = client.post("/api/transactions", headers=headers, json={"amount": 5, "category": "food", "date": future})
        assert r.status_code == 422 and r.json()["field"] == "date"
        assert client.patch(f"/api/transactions/{e['id']}", headers=headers, json={"date": "2026-02-01"}).json()["entry"]["date"] == "2026-02-01"
        items = client.get("/api/transactions?from=2026-02-01&to=2026-02-01", headers=headers).json()["items"]
        assert [i["id"] for i in items] == [e["id"]]
        assert client.get("/api/summary?period=month", headers=headers).json()["expense_minor"] == 0
