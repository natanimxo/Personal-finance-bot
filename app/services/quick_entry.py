"""Quick entry: one plain message logs an entry.

    500 food lunch              -> expense 500, Food, note "lunch"
    +20000 salary               -> income 20,000, Salary
    350 transport mpesa matatu  -> expense 350, Transport, M-Pesa / mobile wallet, note "matatu"

The number comes first; a leading + means income. Words are matched to a
category and an account case-insensitively, including aliases; the first word
that matches each one is used, and every other word becomes the note.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services import validation

# Aliases for the built-in categories and accounts. Names a user gives their own
# categories and accounts (Phase 4) are matched as well.
CATEGORY_ALIASES = {
    "expense": {
        "food": ["food", "lunch", "dinner", "breakfast", "groceries", "grocery", "snack", "snacks", "coffee",
                 "tea", "restaurant", "meal"],
        "transport": ["transport", "matatu", "taxi", "uber", "bolt", "bus", "fuel", "petrol", "boda", "fare", "train"],
        "bills": ["bills", "bill", "rent", "electricity", "power", "water", "internet", "wifi", "airtime", "data", "kplc"],
        "shopping": ["shopping", "clothes", "shoes", "shop"],
        "fun": ["fun", "movie", "movies", "drinks", "party", "outing"],
        "other": ["other", "misc"],
    },
    "income": {
        "salary": ["salary", "pay", "paycheck", "payday", "wage", "wages"],
        "freelance": ["freelance", "gig", "client"],
        "business": ["business", "sales", "sale"],
        "gift": ["gift", "gifts"],
        "other": ["other"],
    },
}
ACCOUNT_ALIASES = {
    "cash": ["cash"],
    "bank": ["bank"],
    "card": ["card", "visa", "mastercard"],
    "mobile_money": ["mpesa", "m-pesa", "mobile", "momo", "wallet", "telebirr", "airtel"],
}

AMOUNT = re.compile(r"^\s*(\+)?\s*(\d[\d,]*(?:\.\d+)?|\.\d+)(?=\s|$)")


@dataclass
class Parsed:
    amount_minor: int
    type: str
    category: Optional[str] = None
    account: Optional[str] = None
    note: str = ""
    unmatched: list = field(default_factory=list)


def looks_like_quick_entry(text: str) -> bool:
    return bool(AMOUNT.match(text or ""))


def _norm(word: str) -> str:
    return word.lower().strip(".,;:!?")


def _names_index(options):
    """{"food": "food", "lunch": "food", ...} from {key: [names...]} (first key wins)."""
    index = {}
    for key, names in options.items():
        for name in [key, *names]:
            for variant in {_norm(name), _norm(name).replace("_", " "), _norm(name).replace("-", "")}:
                index.setdefault(variant, key)
    return index


def parse(text: str, categories: dict = None, accounts: dict = None) -> Optional[Parsed]:
    """Returns None when the text doesn't start with an amount (so it isn't a quick entry).
    Raises ValidationError for an amount that breaks the rules (e.g. 3 decimals).

    `categories` = {"expense": {key: [names]}, "income": {...}}, `accounts` = {key: [names]};
    both default to the built-in lists and aliases."""
    match = AMOUNT.match(text or "")
    if not match:
        return None
    plus, number = match.group(1), match.group(2)
    amount_minor = validation.parse_amount_minor(number)
    words = text[match.end():].split()

    categories = categories or CATEGORY_ALIASES
    accounts = accounts or ACCOUNT_ALIASES
    expense_index = _names_index(categories.get("expense", {}))
    income_index = _names_index(categories.get("income", {}))
    account_index = _names_index(accounts)

    type_ = "income" if plus else "expense"
    category = account = None
    note_words = []
    for word in words:
        w = _norm(word)
        if category is None and type_ == "expense" and w in expense_index:
            category = expense_index[w]
        elif category is None and type_ == "income" and w in income_index:
            category = income_index[w]
        elif category is None and not plus and w in income_index and w not in expense_index and not note_words:
            # "20000 salary": clearly income even without the +
            type_, category = "income", income_index[w]
        elif account is None and (w in account_index or w.replace("-", "") in account_index):
            account = account_index.get(w) or account_index[w.replace("-", "")]
        else:
            note_words.append(word)
    note = " ".join(note_words)
    validation.check_note(note)
    return Parsed(amount_minor=amount_minor, type=type_, category=category, account=account, note=note,
                  unmatched=note_words)
