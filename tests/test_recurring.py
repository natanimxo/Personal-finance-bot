"""Phase 4.7: recurring entries."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import get_conn, init_db
from app.services import periods, recurring, transactions
from app.services.recurring import advance
from app.services.validation import ValidationError
from tests.fake_telegram import UID, Harness, run


@pytest.mark.parametrize("start,anchor,expected", [
    (date(2026, 1, 31), 31, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]),
    (date(2026, 11, 15), 15, [date(2026, 12, 15), date(2027, 1, 15)]),
])
def test_monthly_keeps_its_day_and_clamps_short_months(start, anchor, expected):
    got, day = [], start
    for _ in expected:
        day = advance(day, "monthly", anchor)
        got.append(day)
    assert got == expected


def test_weekly():
    assert advance(date(2026, 11, 23), "weekly", 0) == date(2026, 11, 30)


@pytest.fixture
def db(fresh_db):
    init_db()


def entry_on(day, amount=25000, category="bills", type_="expense", note="Rent"):
    e, _ = transactions.add_entry(UID, amount * 100, type_, category, "bank", note, day)
    return e


def test_rule_from_an_entry_starts_one_period_later(db):
    e = entry_on(date(2026, 11, 1))
    rule = recurring.create_from_entry(UID, e["id"], "monthly")
    assert (rule["next_date"], rule["anchor_day"], rule["note"]) == ("2026-12-01", 1, "Rent")


def test_due_entries_are_created_with_their_own_date(db):
    rule = recurring.create_from_entry(UID, entry_on(date(2026, 9, 1))["id"], "monthly")
    created = recurring.process_due(today=date(2026, 11, 20))   # Oct 1 and Nov 1 were missed
    assert len(created) == 2
    dates = sorted(periods.local_date_of(transactions.get_entry(UID, eid)["occurred_at"]) for _, eid in created)
    assert dates == [date(2026, 10, 1), date(2026, 11, 1)]
    assert recurring.get_rule(UID, rule["id"])["next_date"] == "2026-12-01"


def test_running_again_never_creates_a_duplicate(db):
    recurring.create_from_entry(UID, entry_on(date(2026, 10, 1))["id"], "monthly")
    first = recurring.process_due(today=date(2026, 11, 1))
    again = recurring.process_due(today=date(2026, 11, 1))       # a restart re-runs the job the same day
    later = recurring.process_due(today=date(2026, 11, 30))
    assert len(first) == 1 and again == [] and later == []
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 2


def test_a_run_that_already_claimed_a_date_wins(db):
    """Two overlapping runs: the second sees next_date already moved and skips it."""
    rule = recurring.create_from_entry(UID, entry_on(date(2026, 10, 5))["id"], "monthly")
    with get_conn() as conn:  # simulate the other run having claimed Nov 5 a moment ago
        conn.execute("UPDATE recurring SET next_date = '2026-12-05' WHERE id = ?", (rule["id"],))
    assert recurring.process_due(today=date(2026, 11, 10)) == []


def test_deleted_rule_stops_but_past_entries_stay(db):
    rule = recurring.create_from_entry(UID, entry_on(date(2026, 10, 1))["id"], "monthly")
    recurring.process_due(today=date(2026, 11, 1))
    assert recurring.delete_rule(UID, rule["id"])
    assert recurring.process_due(today=date(2027, 1, 1)) == []
    assert len(transactions.list_recent(UID)) == 2


def test_transfers_cannot_repeat(db):
    t = transactions.add_transfer(UID, 100, "cash", "bank")
    with pytest.raises(ValidationError):
        recurring.create_from_entry(UID, t["id"], "weekly")
    with pytest.raises(ValidationError):
        recurring.create_from_entry(UID, entry_on(date(2026, 11, 1))["id"], "daily")


# --- bot ----------------------------------------------------------------------------
def test_bot_repeat_list_stop(db):
    e = entry_on(periods.today() - timedelta(days=30), amount=999, note="Netflix")

    async def scenario():
        async with Harness() as h:
            out = await h.tap(f"edit:{e['id']}")
            assert any(b["callback_data"] == f"rep:{e['id']}" for b in out.buttons())
            await h.tap(f"rep:{e['id']}")
            out = await h.tap(f"repset:{e['id']}:monthly")
            assert "repeats every month" in out.texts[-1]
            out = await h.tap("set:recurring")
            assert "Netflix" in out.texts[-1] and "every month" in out.texts[-1] and "KES 999" in out.texts[-1]
            rule_id = recurring.list_rules(UID)[0]["id"]
            out = await h.tap(f"repdel:{rule_id}")
            assert "None yet" in out.texts[-1]

    run(scenario())


def test_daily_job_logs_and_messages_with_undo(db):
    # 8 days ago, weekly: the next copy was due yesterday, so it is due whatever the hour now.
    recurring.create_from_entry(UID, entry_on(periods.today() - timedelta(days=8), amount=50, category="food",
                                              note="Gym snack")["id"], "weekly")

    async def scenario():
        async with Harness() as h:
            job = next(j for j in h.app.job_queue.jobs() if j.name == "recurring")
            assert job.job.trigger.interval == timedelta(hours=1)                   # hourly, per user's 06:00
            h.request.sent.clear()
            await job.callback(SimpleNamespace(bot=h.app.bot))
            msgs = [p for e, p in h.request.sent if e == "sendMessage"]
            assert len(msgs) == 1 and msgs[0]["chat_id"] == UID and "Recurring" in msgs[0]["text"]
            assert "Gym snack" in msgs[0]["text"]
            h.request.sent.clear()
            await job.callback(SimpleNamespace(bot=h.app.bot))            # same day again: nothing new
            assert [p for e, p in h.request.sent if e == "sendMessage"] == []
            assert len(transactions.list_recent(UID)) == 2

    run(scenario())


# --- API ----------------------------------------------------------------------------
def test_api_repeat_list_delete(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=Harness().app)) as client:
        r = client.post("/api/transactions", headers=headers,
                        json={"amount": "45000", "type": "income", "category": "salary", "repeat": "monthly"}).json()
        assert r["recurring"]["frequency"] == "monthly"
        bad = client.post("/api/transactions", headers=headers, json={"amount": "5", "category": "food", "repeat": "daily"})
        assert bad.status_code == 422 and len(transactions.list_recent(UID)) == 1   # nothing half-saved
        rules = client.get("/api/recurring", headers=headers).json()["recurring"]
        assert len(rules) == 1 and rules[0]["category_label"] == "💼 Salary"
        assert client.delete(f"/api/recurring/{rules[0]['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/recurring/{rules[0]['id']}", headers=headers).status_code == 404
