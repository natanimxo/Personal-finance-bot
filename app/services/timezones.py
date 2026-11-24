"""Finding a user's timezone: from a shared location, a typed city or UTC offset,
or a pick from a short list per region. Everything is offline (tzdata plus the
small tzfpy lookup table), so no paid or external API is called.
"""
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

logger = logging.getLogger(__name__)

# Region -> common zones, for the picker. Anything else can be typed (a city or UTC+3).
REGIONS = {
    "africa": ["Africa/Lagos", "Africa/Cairo", "Africa/Johannesburg", "Africa/Nairobi", "Africa/Addis_Ababa",
               "Africa/Accra", "Africa/Casablanca", "Africa/Kinshasa", "Africa/Algiers", "Africa/Dar_es_Salaam",
               "Africa/Kampala", "Africa/Khartoum"],
    "americas": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                 "America/Toronto", "America/Mexico_City", "America/Bogota", "America/Lima", "America/Caracas",
                 "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Santiago", "America/Anchorage",
                 "Pacific/Honolulu"],
    "asia": ["Asia/Dubai", "Asia/Riyadh", "Asia/Tehran", "Asia/Karachi", "Asia/Kolkata", "Asia/Kathmandu",
             "Asia/Dhaka", "Asia/Bangkok", "Asia/Jakarta", "Asia/Singapore", "Asia/Manila", "Asia/Shanghai",
             "Asia/Hong_Kong", "Asia/Seoul", "Asia/Tokyo"],
    "europe": ["Europe/London", "Europe/Lisbon", "Europe/Dublin", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
               "Europe/Rome", "Europe/Amsterdam", "Europe/Stockholm", "Europe/Warsaw", "Europe/Athens",
               "Europe/Istanbul", "Europe/Kyiv", "Europe/Moscow"],
    "oceania": ["Australia/Perth", "Australia/Adelaide", "Australia/Brisbane", "Australia/Sydney",
                "Australia/Melbourne", "Pacific/Auckland", "Pacific/Fiji", "Pacific/Port_Moresby", "Pacific/Guam"],
}

# Big cities that aren't zone names themselves.
CITY_ALIASES = {
    "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata", "chennai": "Asia/Kolkata", "hyderabad": "Asia/Kolkata", "calcutta": "Asia/Kolkata",
    "beijing": "Asia/Shanghai", "shenzhen": "Asia/Shanghai", "guangzhou": "Asia/Shanghai",
    "washington": "America/New_York", "boston": "America/New_York", "miami": "America/New_York",
    "atlanta": "America/New_York", "philadelphia": "America/New_York", "nyc": "America/New_York",
    "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles", "la": "America/Los_Angeles",
    "san diego": "America/Los_Angeles", "las vegas": "America/Los_Angeles",
    "houston": "America/Chicago", "dallas": "America/Chicago", "austin": "America/Chicago",
    "montreal": "America/Toronto", "ottawa": "America/Toronto", "rio": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo", "brasilia": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "abuja": "Africa/Lagos", "addis": "Africa/Addis_Ababa", "cape town": "Africa/Johannesburg",
    "pretoria": "Africa/Johannesburg", "durban": "Africa/Johannesburg", "kumasi": "Africa/Accra",
    "mombasa": "Africa/Nairobi", "kisumu": "Africa/Nairobi", "alexandria": "Africa/Cairo",
    "islamabad": "Asia/Karachi", "lahore": "Asia/Karachi", "abu dhabi": "Asia/Dubai", "sharjah": "Asia/Dubai",
    "jeddah": "Asia/Riyadh", "mecca": "Asia/Riyadh", "doha": "Asia/Qatar", "hanoi": "Asia/Bangkok",
    "saigon": "Asia/Ho_Chi_Minh", "ho chi minh city": "Asia/Ho_Chi_Minh", "kiev": "Europe/Kyiv",
    "st petersburg": "Europe/Moscow", "saint petersburg": "Europe/Moscow", "barcelona": "Europe/Madrid",
    "milan": "Europe/Rome", "munich": "Europe/Berlin", "frankfurt": "Europe/Berlin", "hamburg": "Europe/Berlin",
    "manchester": "Europe/London", "birmingham": "Europe/London", "edinburgh": "Europe/London",
    "geneva": "Europe/Zurich", "canberra": "Australia/Sydney", "wellington": "Pacific/Auckland",
}

# Offsets that aren't whole hours have no Etc/GMT zone; use a real zone on that offset.
ODD_OFFSETS = {
    (1, 3, 30): "Asia/Tehran", (1, 4, 30): "Asia/Kabul", (1, 5, 30): "Asia/Kolkata", (1, 5, 45): "Asia/Kathmandu",
    (1, 6, 30): "Asia/Yangon", (1, 9, 30): "Australia/Darwin", (1, 10, 30): "Australia/Lord_Howe",
    (1, 12, 45): "Pacific/Chatham", (-1, 3, 30): "America/St_Johns", (-1, 9, 30): "Pacific/Marquesas",
}
OFFSET = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?:[:.]?(\d{2}))?$")
CANONICAL_PREFIXES = ("Africa/", "America/", "Antarctica/", "Asia/", "Atlantic/", "Australia/", "Europe/",
                      "Indian/", "Pacific/")


@lru_cache(maxsize=1)
def all_zones() -> frozenset:
    return frozenset(z for z in available_timezones() if z not in ("localtime", "Factory"))


def is_valid(name: str) -> bool:
    return bool(name) and name in all_zones()


@lru_cache(maxsize=1)
def _index() -> dict:
    """lower-case name or city -> zone ("europe/berlin", "berlin", "new york", "buenos aires")."""
    index = {}
    for zone in sorted(all_zones()):
        index[zone.lower()] = zone
        name = zone.rsplit("/", 1)[-1].replace("_", " ").lower()
        current = index.get(name)
        # Prefer a real region's zone (America/Havana) over a legacy alias (Cuba).
        if current is None or (zone.startswith(CANONICAL_PREFIXES) and not current.startswith(CANONICAL_PREFIXES)):
            index[name] = zone
    index.update(CITY_ALIASES)
    return index


def parse(text: str):
    """A zone from what the user typed: Europe/Berlin, Berlin, new york, UTC, UTC+3, GMT-5, +5:30. Or None."""
    t = " ".join((text or "").strip().lower().replace("_", " ").split())
    if not t:
        return None
    if t in ("utc", "gmt", "z", "utc+0", "utc-0", "gmt+0", "+0"):
        return "UTC"
    m = OFFSET.match(t.replace(" ", ""))
    if m:
        sign = 1 if m.group(1) == "+" else -1
        hours, minutes = int(m.group(2)), int(m.group(3) or 0)
        if minutes:
            return ODD_OFFSETS.get((sign, hours, minutes))
        if hours == 0:
            return "UTC"
        if (sign > 0 and hours <= 14) or (sign < 0 and hours <= 12):
            return f"Etc/GMT{'-' if sign > 0 else '+'}{hours}"  # Etc/GMT signs are inverted (POSIX)
        return None
    return _index().get(t) or _index().get(t.replace(" ", "_"))


def from_location(latitude: float, longitude: float) -> str:
    """The zone at a point. Falls back to a whole-hour offset from the longitude."""
    try:
        from tzfpy import get_tz

        zone = get_tz(longitude, latitude)
        if is_valid(zone):
            return zone
    except Exception as e:  # missing wheel, or the point is at sea
        logger.warning("Timezone lookup for a location failed: %s", e)
    hours = max(-12, min(14, round(longitude / 15)))
    return "UTC" if hours == 0 else f"Etc/GMT{'-' if hours > 0 else '+'}{abs(hours)}"


def offset_label(zone: str, now: datetime = None) -> str:
    """UTC+3, UTC-5, UTC+5:30, UTC (the offset right now, daylight saving included)."""
    now = now or datetime.now(timezone.utc)
    seconds = int(now.astimezone(ZoneInfo(zone)).utcoffset().total_seconds())
    if seconds == 0:
        return "UTC"
    sign = "+" if seconds > 0 else "-"
    hours, rest = divmod(abs(seconds), 3600)
    return f"UTC{sign}{hours}" + (f":{rest // 60:02d}" if rest else "")


def city(zone: str) -> str:
    """Nairobi, New York, Buenos Aires; UTC+3 for the fixed Etc/GMT zones."""
    if zone == "UTC":
        return "UTC"
    if zone.startswith("Etc/"):
        return offset_label(zone)
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def local_time(zone: str, now: datetime = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.astimezone(ZoneInfo(zone)):%H:%M}"
