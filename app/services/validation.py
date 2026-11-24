"""Input rules shared by the bot and the API. Messages are written for users."""
import re
from decimal import Decimal, InvalidOperation

from app.services import catalog

MAX_AMOUNT = 100_000_000
MAX_NOTE_LENGTH = 200
CURRENCY = re.compile(r"^[A-Z]{3}$")


class ValidationError(ValueError):
    """A ValueError whose message is fit to show the user."""

    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.field = field


AmountError = ValidationError  # older name used by the bot


def _decimal(text: str) -> Decimal:
    cleaned = str(text).strip().replace(",", "").replace(" ", "").replace("\u00a0", "")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", cleaned):
        raise ValidationError("That doesn't look like an amount.", "amount")
    value = Decimal(cleaned)
    if value <= 0:
        raise ValidationError("The amount has to be more than 0.", "amount")
    if -value.as_tuple().exponent > 2 and value != value.quantize(Decimal("0.01")):
        raise ValidationError("Use at most 2 decimal places.", "amount")
    if value > MAX_AMOUNT:
        raise ValidationError(f"That's more than the maximum of {MAX_AMOUNT:,}.", "amount")
    return value


def parse_amount(text: str) -> float:
    """Accepts 1500, 1,500, 1 500 and 1500.50. Positive, at most 2 decimal
    places and at most MAX_AMOUNT; raises ValidationError otherwise."""
    return float(_decimal(text))


def parse_amount_minor(value) -> int:
    """An amount (text or number) as integer cents, with the same rules."""
    if isinstance(value, bool):
        raise ValidationError("That doesn't look like an amount.", "amount")
    if isinstance(value, (int, float)):
        try:
            value = format(Decimal(str(value)).normalize(), "f")
        except InvalidOperation:
            raise ValidationError("That doesn't look like an amount.", "amount")
    return int(_decimal(value) * 100)


def to_minor(amount) -> int:
    """A float amount from older code paths as integer cents."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1")))


def check_type(type_: str) -> str:
    if type_ not in catalog.TYPES:
        raise ValidationError("Type must be expense or income.", "type")
    return type_


def check_note(note) -> str:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValidationError(f"Notes can be up to {MAX_NOTE_LENGTH} characters.", "note")
    return note


def check_currency(code: str) -> str:
    code = (code or "").strip().upper()
    if not CURRENCY.match(code):
        raise ValidationError("Currency must be a 3-letter code, like KES or ETB.", "currency")
    return code


EARLIEST = "2000-01-01"


def check_date(day, now=None):
    """A local date (date or YYYY-MM-DD / user text) that isn't in the future. Returns a date."""
    from datetime import date as _date

    from app.services import periods

    if day is None or day == "":
        return None
    try:
        d = day if isinstance(day, _date) else periods.parse_user_date(str(day), now)
    except ValueError as e:
        raise ValidationError(str(e), "date")
    if d > periods.today(now):
        raise ValidationError("The date can't be in the future.", "date")
    if d.isoformat() < EARLIEST:
        raise ValidationError("That date is too far back.", "date")
    return d
