"""The Mini App's Income tab (in place of Accounts) and Accounts inside Settings."""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import get_conn, init_db
from app.services import categories, prefs, summaries, transactions
from tests.fake_telegram import UID, Harness

STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"
NAIROBI = "Africa/Nairobi"
# Wednesday 25 Nov 2026, 12:00 Nairobi
NOW = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)


@pytest.fixture
def db(fresh_db):
    init_db()
    prefs.set_prefs(UID, "KES", timezone=NAIROBI)


def income(amount, category, stored_utc, type_="income"):
    entry, _ = transactions.add_entry(UID, amount * 100, type_, category, "bank", "", None)
    with get_conn() as conn:
        conn.execute("UPDATE expenses SET occurred_at = ? WHERE id = ?", (stored_utc, entry["id"]))


def test_week_total_change_and_sources(db):
    income(1000, "salary", "2026-11-24T06:00:00")          # this week (from Mon 23 Nov, Nairobi)
    income(120, "freelance", "2026-11-25T06:00:00")
    income(80, "gift", "2026-11-22T20:30:00")               # Sun 22 Nov 23:30 Nairobi: last week
    income(920, "salary", "2026-11-17T06:00:00")            # last week
    income(500, "food", "2026-11-24T06:00:00", "expense")   # an expense: never income
    data = summaries.income_overview(UID, "week", NOW)
    assert data["total_minor"] == 112000 and data["previous_total_minor"] == 100000
    assert data["change_percent"] == 12                       # "+12% vs last week"
    assert [(s["category"], s["total_minor"], s["percent"]) for s in data["by_source"]] == [
        ("salary", 100000, 89), ("freelance", 12000, 11)]
    assert data["from_date"] == "2026-11-23"


def test_month_and_custom_or_hidden_sources(db):
    categories.add_category(UID, "income", "🏦 Interest")
    income(300, "interest", "2026-11-03T06:00:00")
    income(100, "salary", "2026-11-04T06:00:00")
    income(800, "salary", "2026-10-15T06:00:00")             # October
    categories.set_hidden(UID, "income", "interest")          # hidden later: still counted
    data = summaries.income_overview(UID, "month", NOW)
    assert (data["total_minor"], data["previous_total_minor"], data["change_percent"]) == (40000, 80000, -50)
    assert [(s["label"], s["percent"]) for s in data["by_source"]] == [("🏦 Interest", 75), ("💼 Salary", 25)]


def test_nothing_before_means_no_percentage(db):
    income(50, "gift", "2026-11-24T06:00:00")
    assert summaries.income_overview(UID, "week", NOW)["change_percent"] is None
    assert summaries.income_overview(UID, "month", datetime(2026, 12, 2, 9, tzinfo=timezone.utc))["by_source"] == []


def test_api_income(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    transactions.add_entry(UID, 250000, "income", "salary", "bank", "pay", None)
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=Harness().app)) as client:
        r = client.get("/api/income?period=month", headers=headers).json()
        assert r["total_minor"] == 250000 and r["by_source"][0]["label"] == "💼 Salary" and r["currency"] == "KES"
        assert client.get("/api/income?period=year", headers=headers).status_code == 422
        items = client.get(f"/api/transactions?type=income&from={r['from_date']}", headers=headers).json()["items"]
        assert [e["note"] for e in items] == ["pay"]


# --- the app itself ------------------------------------------------------------------------------------
def test_bottom_bar_has_income_instead_of_accounts():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    routes = re.findall(r'data-route="(\w+)"', html)
    assert routes == ["home", "transactions", "budgets", "income", "settings"]
    assert '<span class="ico">💵</span><span>Income</span>' in html


def test_app_wiring():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "income: viewIncome" in js and "accounts: viewAccounts" in js        # Accounts still reachable
    assert 'go("accounts")' in js                                                # from Settings
    assert 'go("add", { type: "income", back: "income" })' in js                 # + Add income
    assert 'go("add", { type: "transfer", back: "accounts" })' in js             # transfers from Accounts
    assert "% vs ${last}" in js
    accounts = js[js.index("async function viewAccounts"):js.index("// ---------------------------------------------------------------- Settings")]
    assert ".filter(Boolean)" in accounts                                       # no stray "null" text
    home = js[js.index("async function viewHome"):js.index("function budgetBar")]
    assert '"Account balances"' in home                                          # Home keeps its balances
