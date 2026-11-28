"""Vertical 1080x1920 promo frames (Reels / TikTok / Shorts) from the raw screenshots.

Each frame is a screenshot inside a plain, generic rounded phone (no real device brand),
centred on a clean gradient with a short headline above it. Rendered with Playwright from a
small HTML page, so it needs no image libraries. Saves demo/output/frames/<theme>/<name>.png.
"""
import base64
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.web.demo import PALETTES  # noqa: E402
from demo.server import launch_browser  # noqa: E402

OUTPUT = ROOT / "demo" / "output"

# (frame name, screenshot it uses, headline)
FRAMES = [
    ("home", "home_month", "See where your money goes"),
    ("add", "add_expense", "Log expenses in seconds"),
    ("budgets", "budgets", "Get warned before you overspend"),
    ("income", "income", "Track every income source"),
    ("transactions", "transactions", "Find any transaction instantly"),
    ("settings", "settings", "Any currency. Any timezone."),
]

BACKGROUNDS = {
    "light": ("linear-gradient(160deg, #dbe9ff 0%, #ece3ff 55%, #ffe3ee 100%)", "#0f172a"),
    "dark": ("linear-gradient(160deg, #0a0f1f 0%, #1a1445 55%, #2b1254 100%)", "#ffffff"),
}

SCREEN_W = 620            # the screenshot, 390 x 844 points, shown at this width
SCREEN_H = round(SCREEN_W * 844 / 390)
STATUS_H = 54
BEZEL = 22


def page_html(theme: str, shot: Path, headline: str) -> str:
    gradient, headline_color = BACKGROUNDS[theme]
    palette = PALETTES[theme]
    data = base64.b64encode(shot.read_bytes()).decode()
    phone_w = SCREEN_W + 2 * BEZEL
    phone_h = STATUS_H + SCREEN_H + 2 * BEZEL
    top = 430
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; margin: 0; }}
      body {{ width: 1080px; height: 1920px; overflow: hidden; background: {gradient};
        font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif; position: relative; }}
      h1 {{ position: absolute; left: 90px; right: 90px; top: 120px; height: 270px; display: flex; align-items: center;
        justify-content: center; text-align: center; font-size: 96px; line-height: 1.08; font-weight: 800;
        letter-spacing: -2px; color: {headline_color}; }}
      .phone {{ position: absolute; left: {(1080 - phone_w) // 2}px; top: {top}px; width: {phone_w}px; height: {phone_h}px;
        padding: {BEZEL}px; border-radius: 96px; background: linear-gradient(145deg, #2b2d33, #0b0b0e);
        box-shadow: 0 70px 130px rgba(15, 23, 42, .38), 0 0 0 3px rgba(255,255,255,.08) inset; }}
      .screen {{ width: {SCREEN_W}px; height: {STATUS_H + SCREEN_H}px; border-radius: 76px; overflow: hidden;
        background: {palette['secondary_bg_color']}; position: relative; }}
      .status {{ height: {STATUS_H}px; display: flex; align-items: center; justify-content: space-between;
        padding: 6px 44px 0; color: {palette['text_color']}; font-size: 21px; font-weight: 700; }}
      .island {{ position: absolute; left: 50%; top: 14px; width: 132px; height: 34px; margin-left: -66px;
        border-radius: 20px; background: #000; }}
      .icons {{ display: flex; gap: 8px; align-items: center; }}
      .bars {{ display: flex; gap: 3px; align-items: flex-end; height: 16px; }}
      .bars i {{ display: block; width: 4px; background: {palette['text_color']}; border-radius: 1px; }}
      .battery {{ width: 31px; height: 15px; border: 2px solid {palette['text_color']}; border-radius: 5px; padding: 1px; }}
      .battery i {{ display: block; height: 100%; width: 78%; background: {palette['text_color']}; border-radius: 2px; }}
      img {{ display: block; width: {SCREEN_W}px; height: {SCREEN_H}px; }}
    </style></head><body>
      <h1>{html.escape(headline)}</h1>
      <div class="phone"><div class="screen">
        <div class="status"><span>9:41</span><span class="icons">
          <span class="bars"><i style="height:6px"></i><i style="height:9px"></i><i style="height:12px"></i><i style="height:15px"></i></span>
          <span class="battery"><i></i></span></span></div>
        <div class="island"></div>
        <img src="data:image/png;base64,{data}">
      </div></div>
    </body></html>"""


def run(themes=("light", "dark"), output: Path = OUTPUT) -> list:
    from playwright.sync_api import sync_playwright

    made = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            page = browser.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1).new_page()
            for theme in themes:
                out_dir = output / "frames" / theme
                out_dir.mkdir(parents=True, exist_ok=True)
                for name, source, headline in FRAMES:
                    shot = output / "raw" / theme / f"{source}.png"
                    page.set_content(page_html(theme, shot, headline), wait_until="load")
                    page.wait_for_timeout(150)
                    target = out_dir / f"{name}.png"
                    page.screenshot(path=str(target))
                    made.append(target)
        finally:
            browser.close()
    return made


if __name__ == "__main__":
    files = run()
    print(f"{len(files)} frames in {OUTPUT / 'frames'}")
