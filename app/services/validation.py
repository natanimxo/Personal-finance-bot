"""Input rules shared by the bot and the API. Messages are written for users."""
import re
from decimal import Decimal, InvalidOperation

from app.services import catalog
from app.strings import t

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
        raise ValidationError(t("error.not_amount"), "amount")
    value = Decimal(cleaned)
    if value <= 0:
        raise ValidationError(t("error.amount_zero"), "amount")
    if -value.as_tuple().exponent > 2 and value != value.quantize(Decimal("0.01")):
        raise ValidationError(t("error.decimals"), "amount")
    if value > MAX_AMOUNT:
        raise ValidationError(t("error.amount_max", max=MAX_AMOUNT), "amount")
    return value


def parse_amount(text: str) -> float:
    """Accepts 1500, 1,500, 1 500 and 1500.50. Positive, at most 2 decimal
    places and at most MAX_AMOUNT; raises ValidationError otherwise."""
    return float(_decimal(text))


def parse_amount_minor(value) -> int:
    """An amount (text or number) as integer cents, with the same rules."""
    if isinstance(value, bool):
        raise ValidationError(t("error.not_amount"), "amount")
    if isinstance(value, (int, float)):
        try:
            value = format(Decimal(str(value)).normalize(), "f")
        except InvalidOperation:
            raise ValidationError(t("error.not_amount"), "amount")
    return int(_decimal(value) * 100)


def to_minor(amount) -> int:
    """A float amount from older code paths as integer cents."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1")))


def check_type(type_: str) -> str:
    if type_ not in catalog.TYPES:
        raise ValidationError(t("error.type"), "type")
    return type_


def check_note(note) -> str:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValidationError(t("error.note_length", max=MAX_NOTE_LENGTH), "note")
    return note


def check_currency(code: str) -> str:
    code = (code or "").strip().upper()
    if not CURRENCY.match(code):
        raise ValidationError(t("error.currency"), "currency")
    return code


def check_timezone(name: str) -> str:
    from app.services import timezones

    name = (name or "").strip()
    if not timezones.is_valid(name):
        raise ValidationError(t("error.timezone"), "timezone")
    return name


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
        raise ValidationError(t("error.date_future"), "date")
    if d.isoformat() < EARLIEST:
        raise ValidationError(t("error.date_too_old"), "date")
    return d
