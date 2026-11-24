"""Every environment variable the app reads, in one place.

The only host-specific inputs are these variables, so the same image runs on
Railway or a plain VPS.
"""
import os


def load_dotenv(path: str = ".env"):
    """Local development: read KEY=value lines from .env. Real environment
    variables win, so this never changes anything on Railway."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and value and key not in os.environ:
                os.environ[key] = value


load_dotenv()


def _env(*names, default=""):
    """First non-empty value among `names` (new name first, legacy names after)."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _resolve_db_path() -> str:
    explicit = _env("DB_PATH")
    if explicit:
        return explicit
    volume = _env("RAILWAY_VOLUME_MOUNT_PATH")
    if volume:
        return os.path.join(volume, "expenses.db")
    # Databases created before the app/ layout lived at ./finance_bot.db.
    # Keep using that file when it exists, so no existing data is orphaned.
    if os.path.exists("finance_bot.db"):
        return "finance_bot.db"
    return os.path.join("data", "expenses.db")


BOT_TOKEN = _env("BOT_TOKEN")
# CHANNEL_ID / CHANNEL_LINK are the documented names; REQUIRED_CHANNEL /
# CHANNEL_INVITE_LINK are the original ones, still accepted so an existing
# Railway service keeps working without renaming its variables.
REQUIRED_CHANNEL = _env("CHANNEL_ID", "REQUIRED_CHANNEL")
CHANNEL_INVITE_LINK = _env("CHANNEL_LINK", "CHANNEL_INVITE_LINK")

DB_PATH = _resolve_db_path()
DB_PATH_SOURCE = (
    "DB_PATH" if _env("DB_PATH")
    else "RAILWAY_VOLUME_MOUNT_PATH" if _env("RAILWAY_VOLUME_MOUNT_PATH")
    else "default"
)

PUBLIC_URL = _env("PUBLIC_URL") or (
    f"https://{_env('RAILWAY_PUBLIC_DOMAIN')}" if _env("RAILWAY_PUBLIC_DOMAIN") else ""
)
WEBHOOK_SECRET = _env("WEBHOOK_SECRET")
# There is no app-wide currency or timezone: every user picks their own on /start
# (stored in user_prefs). Server jobs such as the daily backup run on UTC.
ADMIN_CHAT_ID = int(_env("ADMIN_CHAT_ID")) if _env("ADMIN_CHAT_ID").lstrip("-").isdigit() else None
USE_POLLING = _env("USE_POLLING", default="false").lower() in ("1", "true", "yes")
PORT = int(_env("PORT", default="8000"))

# Railway sets these on every deployment; used only to warn about a missing volume.
ON_RAILWAY = bool(_env("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID"))
RAILWAY_VOLUME_MOUNT_PATH = _env("RAILWAY_VOLUME_MOUNT_PATH")
