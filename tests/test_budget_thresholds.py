"""Phase 5: budget warnings at exactly 80% and over 100%."""
import pytest

from app.db import init_db
from app.services import budgets, transactions
from tests.fake_telegram import UID


@pytest.fixture
def db(fresh_db):
    init_db()
    budgets.set_budget(UID, "food", 1000)


@pytest.mark.parametrize("spent,level,percent", [
    (799.99, None, None),        # just under 80%: quiet
    (800, "near", 80),           # exactly 80%: warn
    (1000, "near", 100),         # exactly the limit: still "near", not over
    (1000.01, "over", 100),      # one cent over: over
    (2500, "over", 250),
])
def test_thresholds(db, spent, level, percent):
    _, warning = transactions.add_entry(UID, round(spent * 100), "expense", "food", "cash")
    assert (warning and warning["level"], warning and warning["percent"]) == (level, percent)


def test_no_budget_no_warning(db):
    _, warning = transactions.add_entry(UID, 999999, "expense", "fun", "cash")
    assert warning is None


def test_income_never_warns(db):
    _, warning = transactions.add_entry(UID, 999999, "income", "salary", "cash")
    assert warning is None
