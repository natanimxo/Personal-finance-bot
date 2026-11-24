"""One process: FastAPI (API, webhook, Mini App files, /healthz) plus the bot.

Telegram delivers bot updates to POST /telegram/webhook, checked against
WEBHOOK_SECRET. The bot falls back to polling when USE_POLLING=true, or when
WEBHOOK_SECRET or an https PUBLIC_URL is missing, so a service that hasn't set
those up yet keeps working (with a warning in the logs).
"""
import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from telegram import MenuButtonWebApp, Update, WebAppInfo

from app import config
from app.strings import t

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
WEBHOOK_PATH = "/telegram/webhook"


def mini_app_url() -> str:
    """The Mini App's https URL, or "" when there is none (Telegram requires https)."""
    url = config.PUBLIC_URL.rstrip("/")
    return url + "/" if url.startswith("https://") else ""


def delivery_mode() -> str:
    if config.USE_POLLING:
        return "polling"
    problems = []
    if not config.WEBHOOK_SECRET:
        problems.append("WEBHOOK_SECRET is not set")
    if not mini_app_url():
        problems.append("there is no https PUBLIC_URL (generate a Railway domain)")
    if problems:
        logger.warning("Webhook mode needs a secret and a public https URL: %s. Falling back to polling.",
                       "; ".join(problems))
        return "polling"
    return "webhook"


async def start_bot(application, mode: str):
    await application.initialize()
    bot = application.bot
    if mode == "webhook":
        await bot.set_webhook(
            url=config.PUBLIC_URL.rstrip("/") + WEBHOOK_PATH,
            secret_token=config.WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    url = mini_app_url()
    if url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=t("menu.button"), web_app=WebAppInfo(url=url)))
    await application.start()
    logger.info("Bot started (%s). Mini App: %s", mode, url or "not available without an https PUBLIC_URL")
    from app.bot.membership import startup_check
    try:
        await startup_check(bot)   # with the gate on: alert the admin about channels the bot isn't admin of
    except Exception as e:
        logger.warning("Channel gate startup check failed: %s", e)


async def stop_bot(application, mode: str):
    if mode == "polling" and application.updater and application.updater.running:
        await application.updater.stop()
    await application.stop()
    await application.shutdown()


def create_app(application=None) -> FastAPI:
    """`application` lets tests pass a bot wired to a fake Telegram."""

    @asynccontextmanager
    async def lifespan(web: FastAPI):
        from app.db import init_db
        from app.main import build_application, check_storage

        init_db()
        check_storage()
        web.state.application = application or build_application()
        web.state.mode = delivery_mode()
        await start_bot(web.state.application, web.state.mode)
        try:
            yield
        finally:
            await stop_bot(web.state.application, web.state.mode)

    web = FastAPI(title="Expense bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    from app.web.api import router
    web.include_router(router)

    @web.middleware("http")
    async def revalidate_app_files(request: Request, call_next):
        """The Mini App's files must never run stale after a deploy: browsers (and
        Telegram's in-app browser) revalidate each time, getting 304 if unchanged."""
        response = await call_next(request)
        if not request.url.path.startswith(("/api/", WEBHOOK_PATH)):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @web.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.error("Unhandled API error on %s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"error": t("api.server_error")})

    @web.get("/healthz")
    async def healthz():
        from app.web.health import health_status

        status, body = await health_status()
        return JSONResponse(status_code=status, content=body)

    @web.post(WEBHOOK_PATH)
    async def telegram_webhook(request: Request):
        received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not config.WEBHOOK_SECRET or not hmac.compare_digest(received, config.WEBHOOK_SECRET):
            return JSONResponse(status_code=403, content={"ok": False})
        application = request.app.state.application
        update = Update.de_json(await request.json(), application.bot)
        await application.update_queue.put(update)
        return {"ok": True}

    web.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="mini-app")
    return web
