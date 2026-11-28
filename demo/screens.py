"""Capture the Mini App's screens in light and dark theme with Playwright.

Phone viewport 390x844 at device scale 3 (1170x2532 pixels, crisp for video), saved as
demo/output/raw/<theme>/<screen>.png. Needs the demo server running (see build.py).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.server import get_json, launch_browser  # noqa: E402

OUTPUT = ROOT / "demo" / "output"
VIEWPORT = {"width": 390, "height": 844}
DEVICE_SCALE = 3
THEMES = ("light", "dark")
SCREENS = ["home_month", "home_week", "transactions", "transactions_filtered", "add_expense", "budgets", "income",
           "settings"]


def new_context(browser, theme: str, timezone_id: str, today: str = None, **extra):
    """A phone-sized browser context in the given theme (and, with `today`, a pinned clock)."""
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE, is_mobile=True, has_touch=True,
                                  color_scheme=theme, locale="en-US", timezone_id=timezone_id, **extra)
    return context


def pin_clock(page, today: str):
    if today:   # the same instant the server pins (15:00 UTC on that day), so "today" agrees everywhere
        y, m, d = map(int, today.split("-"))
        page.clock.set_fixed_time(datetime(y, m, d, 15, tzinfo=timezone.utc))


def open_app(page, base: str, theme: str, today: str = None):
    pin_clock(page, today)
    page.goto(f"{base}/?theme={theme}")
    page.wait_for_selector("#tabs:not([hidden])")
    settle(page)


def settle(page, extra_ms: int = 450):
    """Wait until the app has finished loading the current screen."""
    page.wait_for_function("!document.querySelector('.spinner')")
    page.wait_for_timeout(extra_ms)


def tab(page, route: str):
    page.click(f'button[data-route="{route}"]')
    settle(page)


def period(page, label: str):
    """The This week / This month switch (Home and Income share it)."""
    page.click(f'.seg button:has-text("{label}")')
    settle(page)


def fill_add_form(page):
    """The Add screen, filled in as someone would: amount, category, account, note."""
    page.click("#demo-main")                                     # the main button reads "Add entry" on Home
    settle(page, 300)
    page.fill('input[aria-label="Amount"]', "42.50")
    page.click('.chips[aria-label="Category"] .chip:has-text("Food")')
    page.click('.chips[aria-label="Account"] .chip:has-text("Card")')
    page.fill('textarea[aria-label="Note"]', "Lunch with Sam")
    page.wait_for_timeout(300)


def capture(page, base: str, theme: str, today: str, out_dir: Path):
    """All eight screens for one theme."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def shot(name):
        page.screenshot(path=str(out_dir / f"{name}.png"))

    open_app(page, base, theme, today)
    period(page, "This month")
    shot("home_month")
    period(page, "This week")
    shot("home_week")

    tab(page, "transactions")
    shot("transactions")
    page.click('.seg button:has-text("Expenses")')
    settle(page)
    page.select_option('select[aria-label="All categories"]', "food")
    settle(page)
    shot("transactions_filtered")

    tab(page, "home")
    fill_add_form(page)
    shot("add_expense")                                          # not saved: just look away
    page.goto(f"{base}/?theme={theme}")                          # a clean start for the rest
    page.wait_for_selector("#tabs:not([hidden])")
    settle(page)

    tab(page, "budgets")
    shot("budgets")

    tab(page, "income")
    period(page, "This month")
    shot("income")

    tab(page, "settings")
    shot("settings")


def run(base: str, today: str = None, themes=THEMES, output: Path = OUTPUT) -> list:
    from playwright.sync_api import sync_playwright

    timezone_id = get_json(base, "/api/me")["settings"]["timezone"]
    made = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            for theme in themes:
                context = new_context(browser, theme, timezone_id)
                page = context.new_page()
                out_dir = output / "raw" / theme
                capture(page, base, theme, today, out_dir)
                made += [out_dir / f"{name}.png" for name in SCREENS]
                context.close()
        finally:
            browser.close()
    return made


if __name__ == "__main__":
    from demo.server import demo_server

    with demo_server() as url:
        files = run(url)
    print(f"{len(files)} screenshots in {OUTPUT / 'raw'}")
