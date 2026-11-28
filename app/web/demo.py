"""Demo mode: the Mini App on its own, for promo screenshots and clips. Local only.

What is different from the real app (and why it can't touch anything real):
- only the web app runs: there is no bot, no webhook, and nothing can be sent to Telegram
  (DemoApplication's "bot" swallows every call);
- it uses demo/demo.db (config.DEMO_DB), never DB_PATH, and refuses to start at all next
  to Railway variables or the /data volume (config.demo_problems);
- every request is the one demo user: no Telegram sign-in check, no channel gate;
- instead of telegram.org's script the page loads /demo-telegram.js, which fakes
  Telegram.WebApp and sets the same --tg-theme-* colours Telegram does, so the app looks
  as it does inside Telegram. Pick the theme with ?theme=light or ?theme=dark.
"""
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.strings import t

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TELEGRAM_SCRIPT = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'

# Telegram's default Day and Night themes as the Mini App API reports them (themeParams).
PALETTES = {
    "light": {
        "bg_color": "#ffffff", "text_color": "#000000", "hint_color": "#8e8e93", "link_color": "#007aff",
        "button_color": "#007aff", "button_text_color": "#ffffff", "secondary_bg_color": "#efeff4",
        "header_bg_color": "#ffffff", "bottom_bar_bg_color": "#ffffff", "accent_text_color": "#007aff",
        "section_bg_color": "#ffffff", "section_header_text_color": "#6d6d72", "subtitle_text_color": "#8e8e93",
        "destructive_text_color": "#ff3b30",
    },
    "dark": {
        "bg_color": "#1c1c1d", "text_color": "#ffffff", "hint_color": "#98989e", "link_color": "#3e88f7",
        "button_color": "#3e88f7", "button_text_color": "#ffffff", "secondary_bg_color": "#000000",
        "header_bg_color": "#1c1c1d", "bottom_bar_bg_color": "#1c1c1d", "accent_text_color": "#3e88f7",
        "section_bg_color": "#2c2c2e", "section_header_text_color": "#8d8e93", "subtitle_text_color": "#98989e",
        "destructive_text_color": "#ff453a",
    },
}

DEMO_FIRST_NAME = "Alex"

# Plain JavaScript; __PALETTES__ is filled in below. It stands in for telegram-web-app.js.
STUB = r"""
(() => {
  const PALETTES = __PALETTES__;
  const scheme = new URLSearchParams(location.search).get("theme") === "dark" ? "dark" : "light";
  const params = PALETTES[scheme];
  const root = document.documentElement;
  for (const [key, value] of Object.entries(params)) root.style.setProperty("--tg-theme-" + key.replace(/_/g, "-"), value);
  root.style.colorScheme = scheme;
  root.dataset.demoTheme = scheme;

  // Telegram draws the main button natively under the page, so the page's own bottom bar
  // sits above it. This reproduces that so screenshots match what people see in Telegram.
  const style = document.createElement("style");
  style.textContent = `
    #demo-main { position: fixed; left: 0; right: 0; bottom: 0; height: 58px; z-index: 20; border: 0;
      background: var(--tg-theme-button-color); color: var(--tg-theme-button-text-color);
      font: 600 16px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; letter-spacing: .2px; }
    #demo-main[hidden] { display: none; }
    #demo-main[disabled] { opacity: .6; }
    html.demo-main .tabs { bottom: 58px; }
    html.demo-main body { padding-bottom: calc(68px + 58px); }
    html.demo-main .toast { bottom: calc(90px + 58px); }`;
  document.head.append(style);
  const button = document.createElement("button");
  button.id = "demo-main";
  button.hidden = true;
  let clickHandlers = [];
  button.addEventListener("click", () => clickHandlers.slice().forEach((fn) => fn()));
  document.addEventListener("DOMContentLoaded", () => document.body.append(button));

  const main = {
    isVisible: false,
    setText(text) { button.textContent = text; return main; },
    show() { button.hidden = false; main.isVisible = true; root.classList.add("demo-main"); return main; },
    hide() { button.hidden = true; main.isVisible = false; root.classList.remove("demo-main"); return main; },
    onClick(fn) { clickHandlers.push(fn); return main; },
    offClick(fn) { clickHandlers = clickHandlers.filter((f) => f !== fn); return main; },
    showProgress() { button.disabled = true; return main; },
    hideProgress() { button.disabled = false; return main; },
    enable() { button.disabled = false; return main; },
    disable() { button.disabled = true; return main; },
  };
  const back = { isVisible: false, show() { back.isVisible = true; }, hide() { back.isVisible = false; }, onClick() {}, offClick() {} };

  window.Telegram = { WebApp: {
    initData: "demo", initDataUnsafe: { user: { id: __USER_ID__, first_name: "__FIRST_NAME__" } },
    version: "8.0", platform: "ios", colorScheme: scheme, themeParams: params, isExpanded: true,
    MainButton: main, BackButton: back,
    HapticFeedback: { notificationOccurred() {}, impactOccurred() {}, selectionChanged() {} },
    ready() {}, expand() {}, close() {}, onEvent() {}, offEvent() {},
    setHeaderColor() {}, setBackgroundColor() {}, enableClosingConfirmation() {},
    openTelegramLink() {}, openLink() {},
    showConfirm(message, callback) { if (callback) callback(window.confirm(message)); },
  } };
})();
"""


def telegram_stub() -> str:
    return (STUB.replace("__PALETTES__", json.dumps(PALETTES)).replace("__USER_ID__", str(config.DEMO_USER_ID))
            .replace("__FIRST_NAME__", DEMO_FIRST_NAME))


class DemoBot:
    """Stands in for the Telegram bot: nothing is ever sent."""

    async def send_message(self, *args, **kwargs):
        logger.debug("demo: a message was not sent")

    async def send_document(self, *args, **kwargs):
        logger.debug("demo: a file was not sent")


class DemoApplication:
    bot = DemoBot()


def demo_index() -> str:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert TELEGRAM_SCRIPT in html, "index.html no longer loads telegram-web-app.js"
    return html.replace(TELEGRAM_SCRIPT, '<script src="/demo-telegram.js"></script>')


def create_demo_app() -> FastAPI:
    if not config.DEMO_MODE:
        raise RuntimeError("create_demo_app() is only for DEMO_MODE=true")

    @asynccontextmanager
    async def lifespan(web: FastAPI):
        from app.db import init_db
        from app.services import periods

        init_db()   # demo/demo.db only
        if config.DEMO_TODAY:
            periods.freeze(config.DEMO_TODAY)
        web.state.application = DemoApplication()
        web.state.mode = "demo"
        logger.warning("DEMO MODE: web app only, database %s, no bot, no Telegram sign-in", config.DB_PATH)
        yield

    web = FastAPI(title="Expense bot (demo)", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    from app.web.api import router
    web.include_router(router)

    @web.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @web.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.error("Unhandled API error on %s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"error": t("api.server_error")})

    @web.get("/healthz")
    async def healthz():
        return {"ok": True, "demo": True}

    @web.get("/demo-telegram.js")
    async def stub_script():
        return Response(telegram_stub(), media_type="application/javascript")

    @web.get("/", response_class=HTMLResponse)
    @web.get("/index.html", response_class=HTMLResponse)
    async def index():
        return demo_index()

    web.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="mini-app")
    return web
