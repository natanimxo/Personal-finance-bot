"""Short phone-sized screen recordings of the Mini App (5-10 seconds each), with Playwright.

  add_expense          adding an expense from start to save
  home_week_month      switching Home between week and month
  budget_near_limit    opening a budget that is close to its limit

Saved as demo/output/clips/<clip>-<theme>.webm. A faint ring shows where each tap lands.
The add-expense clip really saves an entry in demo/demo.db and removes it again afterwards.
"""
import glob
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.screens import VIEWPORT, open_app, period, settle, tab  # noqa: E402
from demo.server import get_json, launch_browser  # noqa: E402

OUTPUT = ROOT / "demo" / "output"
VIDEO_SCALE = 2          # recorded at 780x1688
TAP_RING = """
document.addEventListener("pointerdown", (e) => {
  const ring = document.createElement("div");
  ring.style.cssText = `position:fixed;left:${e.clientX - 26}px;top:${e.clientY - 26}px;width:52px;height:52px;
    border-radius:50%;background:rgba(120,120,128,.40);border:2px solid rgba(255,255,255,.75);pointer-events:none;
    z-index:99999;transform:scale(.4);opacity:1;transition:transform .5s ease-out, opacity .5s ease-out`;
  document.documentElement.append(ring);
  requestAnimationFrame(() => { ring.style.transform = "scale(1.3)"; ring.style.opacity = "0"; });
  setTimeout(() => ring.remove(), 650);
}, true);
"""
CLIPS = ["add_expense", "home_week_month", "budget_near_limit"]
MAX_SECONDS = 10


def ffmpeg_path():
    """Playwright's own small ffmpeg (installed by `playwright install ffmpeg`), or None."""
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.path.expanduser("~/AppData/Local/ms-playwright"),
             os.path.expanduser("~/.cache/ms-playwright"), os.path.expanduser("~/Library/Caches/ms-playwright")]
    for root in filter(None, roots):
        found = sorted(glob.glob(os.path.join(root, "ffmpeg-*", "ffmpeg-*")))
        found = [f for f in found if not f.endswith((".txt", ".json"))]
        if found:
            return found[-1]
    return None


def trim_lead_in(video: Path, start: float):
    """Playwright's videos begin while the page is still blank white; cut that part off."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg or start < 0.3:
        return
    trimmed = video.with_suffix(".trim.webm")
    done = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(video), "-c:v", "libvpx-vp9",
                           "-b:v", "0", "-crf", "28", "-cpu-used", "5", "-row-mt", "1", "-an", str(trimmed)],
                          capture_output=True)
    if done.returncode == 0 and trimmed.exists():
        trimmed.replace(video)
    elif trimmed.exists():
        trimmed.unlink()


def clip_add_expense(page, base, theme, today, marks):
    open_app(page, base, theme, today)
    marks["ready"] = time.perf_counter()
    page.wait_for_timeout(900)
    page.click("#demo-main")                                         # "Add entry"
    settle(page, 500)
    page.click('input[aria-label="Amount"]')
    page.locator('input[aria-label="Amount"]').press_sequentially("18.50", delay=140)
    page.wait_for_timeout(300)
    page.click('.chips[aria-label="Category"] .chip:has-text("Food")')
    page.wait_for_timeout(450)
    page.click('textarea[aria-label="Note"]')
    page.locator('textarea[aria-label="Note"]').press_sequentially("Lunch with Sam", delay=55)
    page.wait_for_timeout(600)
    page.click("#demo-main")                                         # "Save"
    page.wait_for_selector("#tabs:not([hidden])")
    settle(page, 1900)


def clip_home_week_month(page, base, theme, today, marks):
    open_app(page, base, theme, today)
    marks["ready"] = time.perf_counter()
    page.wait_for_timeout(1000)
    period(page, "This month")
    page.wait_for_timeout(1300)
    for _ in range(8):                                               # a gentle scroll down...
        page.mouse.wheel(0, 90)
        page.wait_for_timeout(110)
    page.wait_for_timeout(900)
    for _ in range(8):                                               # ...and back
        page.mouse.wheel(0, -90)
        page.wait_for_timeout(60)
    page.wait_for_timeout(500)
    period(page, "This week")
    page.wait_for_timeout(1500)


def clip_budget_near_limit(page, base, theme, today, marks):
    open_app(page, base, theme, today)
    marks["ready"] = time.perf_counter()
    page.wait_for_timeout(900)
    tab(page, "budgets")
    page.wait_for_timeout(1400)
    page.click('.row:has-text("Shopping")')                          # the one at about 95%
    page.wait_for_timeout(2300)
    page.click('.row:has-text("Shopping")')
    page.wait_for_timeout(1200)


FUNCTIONS = {"add_expense": clip_add_expense, "home_week_month": clip_home_week_month,
             "budget_near_limit": clip_budget_near_limit}


def _newest_ids(base):
    return {e["id"] for e in get_json(base, "/api/transactions")["items"]}


def _delete(base, entry_id):
    request = urllib.request.Request(f"{base}/api/transactions/{entry_id}", method="DELETE")
    urllib.request.urlopen(request, timeout=10).read()


def record(browser, base, name, theme, timezone_id, today, output: Path) -> tuple:
    """One clip. Returns (file, seconds)."""
    from demo.screens import new_context

    out_dir = output / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = output / "clips" / ".recording"
    work.mkdir(exist_ok=True)
    context = new_context(browser, theme, timezone_id, record_video_dir=str(work),
                          record_video_size={"width": VIEWPORT["width"] * VIDEO_SCALE,
                                             "height": VIEWPORT["height"] * VIDEO_SCALE})
    context.add_init_script(TAP_RING)
    page = context.new_page()
    before = _newest_ids(base) if name == "add_expense" else set()
    started = time.perf_counter()
    marks = {}
    try:
        FUNCTIONS[name](page, base, theme, today, marks)
        ended = time.perf_counter()
    finally:
        video = page.video
        context.close()                                              # writes the video file
    target = out_dir / f"{name}-{theme}.webm"
    if target.exists():
        target.unlink()
    Path(video.path()).replace(target)
    lead_in = marks.get("ready", started) - started                    # blank time before the app showed
    trim_lead_in(target, lead_in - 0.4)
    seconds = ended - started - max(0.0, lead_in - 0.4)
    if name == "add_expense":                                        # leave the demo data as it was
        for entry in get_json(base, "/api/transactions")["items"]:
            if entry["id"] not in before and entry["note"] == "Lunch with Sam" and entry["amount_minor"] == 1850:
                _delete(base, entry["id"])
    return target, seconds


def run(base: str, today: str = None, themes=("light", "dark"), output: Path = OUTPUT) -> list:
    from playwright.sync_api import sync_playwright

    from demo.screens import new_context

    timezone_id = get_json(base, "/api/me")["settings"]["timezone"]
    made = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            warm = new_context(browser, "light", timezone_id)      # an unrecorded visit, so the first clip isn't slow
            open_app(warm.new_page(), base, "light", today)
            warm.close()
            for theme in themes:
                for name in CLIPS:
                    try:
                        target, seconds = record(browser, base, name, theme, timezone_id, today, output)
                        if seconds > MAX_SECONDS:                    # a hiccup made it long: once more
                            target, seconds = record(browser, base, name, theme, timezone_id, today, output)
                    except Exception as e:
                        if "ffmpeg" in str(e).lower() or "Executable doesn't exist" in str(e):
                            raise SystemExit("Video recording needs Playwright's small encoder: "
                                             "python -m playwright install ffmpeg")
                        raise
                    print(f"  {target.name}: about {seconds:.0f} s")
                    made.append(target)
        finally:
            browser.close()
    work = output / "clips" / ".recording"
    for leftover in work.glob("*"):
        leftover.unlink()
    work.rmdir()
    return made


if __name__ == "__main__":
    from demo.server import demo_server

    with demo_server() as url:
        files = run(url)
    print(f"{len(files)} clips in {OUTPUT / 'clips'}")
