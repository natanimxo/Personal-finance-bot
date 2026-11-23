"""CSV export of all of a user's entries, built to open cleanly in Excel and Google Sheets.

- UTF-8 with a byte-order mark, so Excel reads names and notes in any script.
- Dates as YYYY-MM-DD (the local date it happened): both apps read them as dates.
- Amounts as plain numbers with a dot and no thousands separator; expenses
  negative and income positive, so a column sum is the net. Transfers are
  positive and listed with both accounts.
- Text that starts with = + - @ is prefixed with ' so a spreadsheet never runs it
  as a formula (CSV injection).
"""
import csv
import io

from app.db import get_conn
from app.services import accounts, catalog, periods, prefs

HEADER = ["Date", "Type", "Category", "Account", "To account", "Amount", "Currency", "Note"]


def _safe(text: str) -> str:
    text = text or ""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _amount(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    return f"{sign}{whole}.{cents:02d}"


def csv_bytes(user_id: int) -> bytes:
    currency = prefs.get_prefs(user_id)["currency"]
    names = accounts.names(user_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT occurred_at, type, category, account, to_account, amount_minor, note FROM expenses "
            "WHERE user_id = ? ORDER BY occurred_at, id",
            (user_id,),
        ).fetchall()
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for r in rows:
        if r["type"] == "transfer":
            category, signed = "Transfer", r["amount_minor"]
        else:
            category = catalog.label_for(r["category"], r["type"])
            signed = r["amount_minor"] if r["type"] == "income" else -r["amount_minor"]
        writer.writerow([
            periods.local_date_of(r["occurred_at"]).isoformat(),
            r["type"].capitalize(),
            _safe(_plain(category)),
            _safe(_plain(names.get(r["account"], r["account"]))),
            _safe(_plain(names.get(r["to_account"], r["to_account"] or ""))) if r["to_account"] else "",
            _amount(signed),
            currency,
            _safe(r["note"]),
        ])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def _plain(label: str) -> str:
    """Labels without their leading emoji ("🍔 Food" -> "Food"), easier to filter on."""
    parts = (label or "").split(" ", 1)
    return parts[1] if len(parts) == 2 and not parts[0].isalnum() else (label or "")


def filename() -> str:
    return f"expenses-{periods.today().isoformat()}.csv"
