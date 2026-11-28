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


# --- demo mode (local only) -------------------------------------------------------------------
# DEMO_MODE=true runs ONLY the web app, against demo/demo.db, as one demo user, with no
# Telegram sign-in check and no channel gate. It is for promo screenshots and clips, so it
# refuses to start anywhere near production: see demo_problems().
DEMO_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "demo.db")
DEMO_USER_ID = 424242


def demo_problems(environ) -> list:
    """Why demo mode must not start with these environment variables ([] means it may)."""
    problems = []
    railway = sorted(name for name in environ if name.startswith("RAILWAY_"))
    if railway:
        problems.append("RAILWAY_* variables are set (" + ", ".join(railway) + "): this looks like Railway")
    raw = (environ.get("DB_PATH") or "").strip().replace("\\", "/")
    if raw == "/data" or raw.startswith("/data/"):
        problems.append(f"DB_PATH points at {raw}, the production volume")
    return problems


DEMO_MODE = _env("DEMO_MODE", default="false").lower() in ("1", "true", "yes")
if DEMO_MODE:
    _problems = demo_problems(os.environ)
    if _problems:
        raise SystemExit("DEMO_MODE refuses to start: " + "; ".join(_problems) + ". Nothing was touched.")
DEMO_PORT = int(_env("DEMO_PORT", default="8800"))
DEMO_TODAY = _env("DEMO_TODAY")   # YYYY-MM-DD: pin the demo's "today" so screenshots never change


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


BOT_TOKEN = "" if DEMO_MODE else _env("BOT_TOKEN")   # a demo never even loads a real token
# The channel gate is not configured here: the channels and the on/off switch live in
# the database and are managed with admin commands (app/services/gate.py).


DB_PATH = DEMO_DB if DEMO_MODE else _resolve_db_path()   # never DB_PATH in demo mode
DB_PATH_SOURCE = (
    "demo" if DEMO_MODE
    else "DB_PATH" if _env("DB_PATH")
    else "RAILWAY_VOLUME_MOUNT_PATH" if _env("RAILWAY_VOLUME_MOUNT_PATH")
    else "default"
)

PUBLIC_URL = "" if DEMO_MODE else _env("PUBLIC_URL") or (
    f"https://{_env('RAILWAY_PUBLIC_DOMAIN')}" if _env("RAILWAY_PUBLIC_DOMAIN") else ""
)
WEBHOOK_SECRET = "" if DEMO_MODE else _env("WEBHOOK_SECRET")
# There is no app-wide currency or timezone: every user picks their own on /start
# (stored in user_prefs). Server jobs such as the daily backup run on UTC.
ADMIN_CHAT_ID = (None if DEMO_MODE else
                 int(_env("ADMIN_CHAT_ID")) if _env("ADMIN_CHAT_ID").lstrip("-").isdigit() else None)
USE_POLLING = _env("USE_POLLING", default="false").lower() in ("1", "true", "yes")
PORT = int(_env("PORT", default="8000"))

# Railway sets these on every deployment; used only to warn about a missing volume.
ON_RAILWAY = bool(_env("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID"))
RAILWAY_VOLUME_MOUNT_PATH = _env("RAILWAY_VOLUME_MOUNT_PATH")
