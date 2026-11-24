"""Phase 4.8: CSV export that opens in Excel and Google Sheets."""
import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import init_db
from app.services import accounts, export, prefs, transactions
from tests.fake_telegram import UID, Harness, run


@pytest.fixture
def db(fresh_db):
    init_db()
    prefs.set_prefs(UID, "ETB")
    transactions.add_entry(UID, 4500000, "income", "salary", "bank", "November pay", date(2026, 11, 1))
    transactions.add_entry(UID, 150050, "expense", "food", "mobile_money", "Groceries, \"big\" shop", date(2026, 11, 3))
    transactions.add_entry(UID, 2000, "expense", "fun", "cash", "=HYPERLINK(\"http://x\")", date(2026, 11, 4))
    transactions.add_transfer(UID, 300000, "bank", "cash", "ATM", date(2026, 11, 5))
    accounts.rename_account(UID, "mobile_money", "ቴሌብር Telebirr")


def rows(data: bytes):
    assert data.startswith("\ufeff".encode("utf-8"))           # BOM: Excel reads UTF-8 correctly
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


def test_csv_contents(db):
    table = rows(export.csv_bytes(UID))
    assert table[0] == export.HEADER
    assert table[1:] == [
        ["2026-11-01", "Income", "Salary", "Bank", "", "45000.00", "ETB", "November pay"],
        ["2026-11-03", "Expense", "Food", "ቴሌብር Telebirr", "", "-1500.50", "ETB", "Groceries, \"big\" shop"],
        ["2026-11-04", "Expense", "Fun", "Cash", "", "-20.00", "ETB", "'=HYPERLINK(\"http://x\")"],
        ["2026-11-05", "Transfer", "Transfer", "Bank", "Cash", "3000.00", "ETB", "ATM"],
    ]


def test_csv_shape_for_spreadsheets(db):
    data = export.csv_bytes(UID)
    assert b"\r\n" in data                                       # CRLF rows
    for row in rows(data)[1:]:
        date.fromisoformat(row[0])                               # every date is ISO
        float(row[5])                                            # every amount is a plain number
        assert "," not in row[5]


def test_empty_export_has_the_header(fresh_db):
    init_db()
    assert rows(export.csv_bytes(UID)) == [export.HEADER]


def test_bot_sends_the_file(db):
    async def scenario():
        async with Harness() as h:
            await h.tap("set:export")
            await h.text("/export")
            docs = [p for e, p in h.request.calls if e == "sendDocument"]
            assert len(docs) == 2 and docs[0]["chat_id"] == UID
            filename, content, _ = h.request.documents[0]
            assert filename.startswith("expenses-") and filename.endswith(".csv")
            assert rows(content)[1][1] == "Income"

    run(scenario())


def test_mini_app_export_goes_to_the_chat(db, monkeypatch):
    from app.web.auth import make_init_data
    from app.web.server import create_app

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setattr(config, "PUBLIC_URL", "https://example.test")
    harness = Harness()
    headers = {"Authorization": "tma " + make_init_data({"id": UID}, config.BOT_TOKEN)}
    with TestClient(create_app(application=harness.app)) as client:
        assert client.post("/api/export", headers=headers).json() == {"sent": True}
        assert len(harness.request.documents) == 1
