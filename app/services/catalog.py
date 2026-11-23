"""Categories and accounts: the one list the bot and the Mini App both use."""

ACCOUNTS = [
    ("cash", "💵 Cash"),
    ("bank", "🏦 Bank"),
    ("card", "💳 Card"),
    ("mobile_money", "📱 Mobile Wallets"),
]

CATEGORIES = [
    ("food", "🍔 Food"),
    ("transport", "🚗 Transport"),
    ("bills", "🧾 Bills"),
    ("shopping", "🛍️ Shopping"),
    ("fun", "🎉 Fun"),
    ("other", "📦 Other"),
]

INCOME_CATEGORIES = [
    ("salary", "💼 Salary"),
    ("freelance", "🧑‍💻 Freelance"),
    ("business", "🏢 Business"),
    ("gift", "🎁 Gift"),
    ("other", "📦 Other"),
]

TYPES = ("expense", "income")
ACCOUNT_LABELS = dict(ACCOUNTS)
CATEGORY_LABELS = dict(CATEGORIES)
INCOME_CATEGORY_LABELS = dict(INCOME_CATEGORIES)


def categories_for(type_: str):
    return INCOME_CATEGORIES if type_ == "income" else CATEGORIES


def label_for(category_key: str, type_: str) -> str:
    table = INCOME_CATEGORY_LABELS if type_ == "income" else CATEGORY_LABELS
    return table.get(category_key, f"📦 {category_key}")


def account_label(account_key: str) -> str:
    return ACCOUNT_LABELS.get(account_key, account_key)


def as_json():
    return {
        "types": list(TYPES),
        "categories": {
            "expense": [{"key": k, "label": v} for k, v in CATEGORIES],
            "income": [{"key": k, "label": v} for k, v in INCOME_CATEGORIES],
        },
        "accounts": [{"key": k, "label": v} for k, v in ACCOUNTS],
    }
