"""How amounts are shown: the user's currency, thousands separators, and
decimals only when there are cents. "KES 1,500", "KES 1,500.50", "−KES 200"."""

MINUS = "\u2212"


def fmt(minor: int, currency: str, sign: bool = False) -> str:
    """`sign=True` puts + on positive amounts too (− is always shown)."""
    minor = int(minor or 0)
    whole, cents = divmod(abs(minor), 100)
    number = f"{whole:,}" + (f".{cents:02d}" if cents else "")
    prefix = MINUS if minor < 0 else ("+" if sign and minor > 0 else "")
    return f"{prefix}{currency} {number}"
