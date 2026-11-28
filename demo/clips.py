"""Short phone-sized screen recordings of the Mini App (5-10 seconds each), with Playwright.

  add_expense          adding an expense from start to save
  home_week_month      switching Home between week and month
  budget_near_limit    opening a budget that is close to its limit

Saved as demo/output/clips/<clip>-<theme>.webm. A faint ring shows where each tap lands.
The add-expense clip really saves an entry in demo/demo.db and removes it again afterwards.
"""
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo import frames  # noqa: E402
from demo.screens import VIEWPORT, open_app, period, settle, tab  # noqa: E402
from demo.server import get_json, launch_browser  # noqa: E402
from app.web.demo import PALETTES  # noqa: E402

OUTPUT = ROOT / "demo" / "output"
VIDEO_SCALE = 2          # frames are captured at 780x1688 (2x the 390x844 phone), so the app fills the whole video
FPS = 30
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
HEADLINES = {"add_expense": "Log expenses in seconds", "home_week_month": "See where your money goes",
             "budget_near_limit": "Get warned before you overspend"}
MAX_SECONDS = 10


def ffmpeg_path() -> str:
    """A full ffmpeg (with the H.264 encoder libx264): on PATH, or from the imageio-ffmpeg package."""
    found = shutil.which("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg
            found = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            found = None
    if not found:
        raise SystemExit("MP4 clips need ffmpeg with H.264 (libx264). Install it (Windows: winget install Gyan.FFmpeg; "
                         "macOS: brew install ffmpeg) or pip install imageio-ffmpeg")
    return found


def encode(frames_dir: Path, shots: list, target: Path):
    """JPEG screencast frames with timestamps -> a 30 fps H.264 MP4 (the screen only repaints on change)."""
    ffmpeg = ffmpeg_path()
    lines = ["ffconcat version 1.0"]
    for i, (path, seconds) in enumerate(shots):
        nxt = shots[i + 1][1] if i + 1 < len(shots) else seconds + 0.6
        lines += [f"file '{path.name}'", f"duration {max(nxt - seconds, 0.001):.4f}"]
    lines.append(f"file '{shots[-1][0].name}'")
    listing = frames_dir / "list.txt"
    listing.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", f"fps={FPS},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-crf", "17",
                    "-preset", "medium", "-movflags", "+faststart", "-an", str(target)], check=True)


def duration(video: Path) -> float:
    """Length in seconds, read from ffmpeg's own report."""
    report = subprocess.run([ffmpeg_path(), "-i", str(video)], capture_output=True, text=True).stderr
    h, m, sec = re.search(r"Duration: (\d+):(\d+):([\d.]+)", report).groups()
    return int(h) * 3600 + int(m) * 60 + float(sec)


def compose(raw: Path, theme: str, layers: tuple, target: Path):
    """The clip inside the phone frame (1080x1920): back layer, the app with rounded corners, front layer."""
    back, front, mask = layers
    secondary = PALETTES[theme]["secondary_bg_color"].lstrip("#")
    graph = (f"[1:v]scale={frames.SCREEN_W}:{frames.SCREEN_H}:flags=lanczos,"
             f"pad={frames.SCREEN_W}:{frames.STATUS_H + frames.SCREEN_H}:0:{frames.VIDEO_Y}:color=0x{secondary},format=rgba[app];"
             f"[3:v]format=gray[m];[app][m]alphamerge[round];"
             f"[0:v][round]overlay={frames.SCREEN_X}:{frames.SCREEN_Y}:shortest=1[a];"
             f"[a][2:v]overlay=0:0:format=auto:shortest=1,format=yuv420p[out]")
    subprocess.run([ffmpeg_path(), "-v", "error", "-y", "-loop", "1", "-i", str(back), "-i", str(raw), "-loop", "1",
                    "-i", str(front), "-loop", "1", "-i", str(mask), "-filter_complex", graph, "-map", "[out]",
                    "-t", f"{duration(raw):.2f}", "-r", str(FPS), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                    "-movflags", "+faststart", "-an", str(target)], check=True)


def clip_add_expense(page, base, theme, today, marks):
    open_app(page, base, theme, today)
    marks["start"]()
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
    marks["start"]()
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
    marks["start"]()
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


def phone_context(browser, theme: str, timezone_id: str):
    """A 780x1688 window showing the 390x844 phone layout at 2x, like a phone's own screen.

    The screen recording always has the size of the window in CSS pixels, so the window itself is
    twice as big and the page is told (through its viewport meta tag) to lay out 390 points across.
    """
    context = browser.new_context(viewport={"width": VIEWPORT["width"] * VIDEO_SCALE, "height": VIEWPORT["height"] * VIDEO_SCALE},
                                  device_scale_factor=1, is_mobile=True, has_touch=True, color_scheme=theme,
                                  locale="en-US", timezone_id=timezone_id)

    def phone_layout(route):
        if route.request.resource_type != "document":
            return route.continue_()
        response = route.fetch()
        body = re.sub(r'(<meta name="viewport" content=")[^"]*"', rf'\g<1>width={VIEWPORT["width"]}"', response.text())
        route.fulfill(response=response, body=body)

    context.route("**/*", phone_layout)
    return context


def record(browser, base, name, theme, timezone_id, today, output: Path) -> tuple:
    """One clip: records the phone-sized page at 2x. Returns (raw mp4, seconds)."""
    raw_dir = output / "clips" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    context = phone_context(browser, theme, timezone_id)
    context.add_init_script(TAP_RING)
    page = context.new_page()
    before = _newest_ids(base) if name == "add_expense" else set()
    shots = []
    work = Path(tempfile.mkdtemp(prefix="clip-", dir=str(output)))
    cdp = context.new_cdp_session(page)

    def on_frame(params):
        path = work / f"f{len(shots):05d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        shots.append((path, params["metadata"]["timestamp"]))
        cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    cdp.on("Page.screencastFrame", on_frame)
    marks = {}
    try:
        def start_recording():
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": VIEWPORT["width"] * VIDEO_SCALE,
                                              "maxHeight": VIEWPORT["height"] * VIDEO_SCALE, "everyNthFrame": 1})
        marks["start"] = start_recording            # each clip calls this once the app is showing
        FUNCTIONS[name](page, base, theme, today, marks)
        page.wait_for_timeout(300)
        cdp.send("Page.stopScreencast")
        if not shots:
            raise RuntimeError("no frames were captured")
        shots.sort(key=lambda s: s[1])
        t0 = shots[0][1]
        shots = [(path, ts - t0) for path, ts in shots]
        target = raw_dir / f"{name}-{theme}.mp4"
        encode(work, shots, target)
        seconds = shots[-1][1] + 0.6
    finally:
        context.close()
        shutil.rmtree(work, ignore_errors=True)
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
    layer_dir = output / "clips" / ".layers"
    framed_dir = output / "clips" / "framed"
    framed_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            warm = new_context(browser, "light", timezone_id)      # an unrecorded visit, so the first clip isn't slow
            open_app(warm.new_page(), base, "light", today)
            warm.close()
            page = browser.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1).new_page()
            for theme in themes:
                for name in CLIPS:
                    layers = frames.clip_layers(page, theme, HEADLINES[name], layer_dir)
                    target, seconds = record(browser, base, name, theme, timezone_id, today, output)
                    if seconds > MAX_SECONDS:                        # a hiccup made it long: once more
                        target, seconds = record(browser, base, name, theme, timezone_id, today, output)
                    compose(target, theme, layers, framed_dir / f"{name}-{theme}.mp4")
                    print(f"  {name}-{theme}: about {seconds:.0f} s (raw and framed)")
                    made.append(target)
        finally:
            browser.close()
    shutil.rmtree(layer_dir, ignore_errors=True)
    return made


if __name__ == "__main__":
    from demo.server import demo_server

    with demo_server() as url:
        files = run(url)
    print(f"{len(files)} clips (raw and framed) in {OUTPUT / 'clips'}")
