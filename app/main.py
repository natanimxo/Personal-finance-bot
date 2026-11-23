"""Builds the bot Application; main() starts the web server that runs it (app/web/server.py)."""
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults

from app import config
from app.bot.conversations import FLOW_TIMEOUT, register_handlers
from app.bot.ratelimit import SendRateLimiter
from app.db import init_db
from app.services.backup import daily_backup_job
from app.services.recap import send_weekly_recap

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per Telegram call is noise at 1,000 users
logger = logging.getLogger(__name__)

RECAP_TIME = time(hour=8, minute=0)
# python-telegram-bot 20+ numbers days 0=Sunday ... 6=Saturday, so Monday is 1.
RECAP_DAYS = (1,)
BACKUP_TIME = time(hour=3, minute=0)


def build_application(request=None, flow_timeout: int = FLOW_TIMEOUT) -> Application:
    tz = ZoneInfo(config.APP_TIMEZONE)
    builder = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        # Keeps sent messages under Telegram's limits (30/s overall, 20/min per
        # group) and retries after a 429 instead of failing. See ratelimit.py.
        .rate_limiter(SendRateLimiter(max_retries=3))
    )
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    register_handlers(app, flow_timeout)
    app.job_queue.run_daily(send_weekly_recap, time=RECAP_TIME.replace(tzinfo=tz), days=RECAP_DAYS, name="weekly_recap")
    app.job_queue.run_daily(daily_backup_job, time=BACKUP_TIME.replace(tzinfo=tz), name="daily_backup")
    return app


def check_storage():
    """Log where the database lives, and shout if Railway would wipe it."""
    path = os.path.abspath(config.DB_PATH)
    logger.info("Database: %s (from %s)", path, config.DB_PATH_SOURCE)
    volume = config.RAILWAY_VOLUME_MOUNT_PATH
    if config.ON_RAILWAY and (not volume or not path.startswith(os.path.abspath(volume))):
        logger.warning(
            "!!! Running on Railway but the database (%s) is not on a volume. "
            "Every redeploy will WIPE all user data. Attach a volume and set DB_PATH inside it. !!!",
            path,
        )


def main():
    """Serve the Mini App, API and webhook with uvicorn; the bot runs in the same event loop."""
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")
    import uvicorn

    from app.web.server import create_app

    uvicorn.run(create_app(), host="0.0.0.0", port=config.PORT, log_level="info", proxy_headers=True)


if __name__ == "__main__":
    main()
