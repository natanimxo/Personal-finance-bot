"""Starts the bot. (Phase 3 adds the web server and webhook; for now it polls.)"""
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults

from app import config
from app.bot.conversations import FLOW_TIMEOUT, register_handlers
from app.db import init_db
from app.services.recap import send_weekly_recap

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

RECAP_TIME = time(hour=8, minute=0)
# python-telegram-bot 20+ numbers days 0=Sunday ... 6=Saturday, so Monday is 1.
RECAP_DAYS = (1,)


def build_application(request=None, flow_timeout: int = FLOW_TIMEOUT) -> Application:
    builder = Application.builder().token(config.BOT_TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML))
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    register_handlers(app, flow_timeout)
    app.job_queue.run_daily(
        send_weekly_recap,
        time=RECAP_TIME.replace(tzinfo=ZoneInfo(config.APP_TIMEZONE)),
        days=RECAP_DAYS,
        name="weekly_recap",
    )
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
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")
    init_db()
    check_storage()
    app = build_application()
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
