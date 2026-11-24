"""Global error handler: log the full error, alert the admin at most once a minute."""
import html
import logging
import time

from telegram.ext import ContextTypes

from app import config
from app.strings import t

logger = logging.getLogger(__name__)

ALERT_INTERVAL = 60  # seconds


class AlertThrottle:
    def __init__(self, interval: float = ALERT_INTERVAL, clock=time.monotonic):
        self.interval = interval
        self.clock = clock
        self.last = None
        self.suppressed = 0

    def allow(self) -> bool:
        now = self.clock()
        if self.last is None or now - self.last >= self.interval:
            self.last = now
            return True
        self.suppressed += 1
        return False


throttle = AlertThrottle()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error("Unhandled error while handling an update", exc_info=error)
    if config.ADMIN_CHAT_ID is None or not throttle.allow():
        return
    where = ""
    if getattr(update, "effective_user", None):
        where = t("admin.error_where", user_id=update.effective_user.id)
    skipped = t("admin.error_skipped", n=throttle.suppressed) if throttle.suppressed else ""
    throttle.suppressed = 0
    error_text = f"{html.escape(type(error).__name__)}: {html.escape(str(error))[:500]}"
    text = t("admin.error_alert", where=where, error=error_text, skipped=skipped)
    try:
        await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=text)
    except Exception as e:
        logger.warning(f"Couldn't send the error alert to the admin: {e}")
