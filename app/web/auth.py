"""Telegram Mini App authentication.

The page sends Telegram.WebApp.initData as `Authorization: tma <initData>`. It is
validated exactly as Telegram specifies
(https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):

  data_check_string = every field except hash, sorted by key, as key=value lines
  secret            = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
  valid             = hex(HMAC_SHA256(secret, data_check_string)) == hash

and auth_date must be under 24 hours old. The user id comes from the validated
data only; a user_id sent by the client is never used.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE = 24 * 60 * 60


class InitDataError(Exception):
    pass


def data_check_string(fields: dict) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")


def sign(fields: dict, bot_token: str) -> str:
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string(fields).encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE, now: float = None) -> dict:
    """Returns the Telegram user dict, or raises InitDataError."""
    if not init_data:
        raise InitDataError("missing initData")
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        raise InitDataError("malformed initData")
    received = fields.get("hash", "")
    if not received or not hmac.compare_digest(sign(fields, bot_token), received):
        raise InitDataError("bad signature")
    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError:
        raise InitDataError("missing auth_date")
    if (now or time.time()) - auth_date > max_age:
        raise InitDataError("initData expired")
    try:
        user = json.loads(fields["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise InitDataError("no user in initData")
    return user


def make_init_data(user: dict, bot_token: str, auth_date: int = None, **extra) -> str:
    """Build signed initData (for tests and the local preview script)."""
    from urllib.parse import urlencode

    fields = {"auth_date": str(auth_date or int(time.time())), "user": json.dumps(user, separators=(",", ":")),
              "query_id": "AAH-test", **{k: str(v) for k, v in extra.items()}}
    fields["hash"] = sign(fields, bot_token)
    return urlencode(fields)
