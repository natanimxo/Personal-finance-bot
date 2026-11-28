"""Vertical 1080x1920 promo frames (Reels / TikTok / Shorts) from the raw screenshots.

Each frame is a screenshot inside a plain, generic rounded phone (no real device brand),
centred on a clean gradient with a short headline above it. Rendered with Playwright from a
small HTML page, so it needs no image libraries. Saves demo/output/frames/<theme>/<name>.png.
Also draws the two text frames (intro, cta) and the layers that put a clip inside the same phone.
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
    ("transactions", "transactions", "Find any transaction fast"),
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


# a clip is laid between two layers: bg (gradient, headline, phone, empty screen) and fg (bezel ring, status bar)
FG_CSS = f"""html, body {{ background: transparent !important; }} h1 {{ visibility: hidden; }}
      .phone {{ background: none !important; box-shadow: none !important; }}
      .screen {{ background: transparent !important; box-shadow: 0 0 0 {BEZEL}px #17181c, 0 0 0 {BEZEL + 3}px rgba(255,255,255,.10); }}
      .status {{ position: relative; z-index: 2; }}"""
BG_CSS = ".status, .island { visibility: hidden; }"
SCREEN_X = (1080 - (SCREEN_W + 2 * BEZEL)) // 2 + BEZEL      # where the screen starts on the 1080x1920 frame
SCREEN_Y = 430 + BEZEL
VIDEO_Y = STATUS_H                                           # the app starts below the status bar


def page_html(theme: str, shot: Path, headline: str, mode: str = "still") -> str:
    """mode: still = the full frame; bg = phone with an empty screen (a clip goes on it); fg = only the bezel and status bar."""
    gradient, headline_color = BACKGROUNDS[theme]
    palette = PALETTES[theme]
    data = base64.b64encode(shot.read_bytes()).decode() if shot else ""
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
      {FG_CSS if mode == "fg" else ""}
      {BG_CSS if mode == "bg" else ""}
    </style></head><body>
      <h1>{html.escape(headline)}</h1>
      <div class="phone"><div class="screen">
        <div class="status"><span>9:41</span><span class="icons">
          <span class="bars"><i style="height:6px"></i><i style="height:9px"></i><i style="height:12px"></i><i style="height:15px"></i></span>
          <span class="battery"><i></i></span></span></div>
        <div class="island"></div>
        {f'<img src="data:image/png;base64,{data}">' if mode == "still" else ""}
      </div></div>
    </body></html>"""


LOGO = ROOT / "demo" / "assets" / "logo.png"
BOT = "@Wallet_buddy_bot"

# a plain wallet icon, used only if demo/assets/logo.png is missing
WALLET_SVG = """<svg viewBox="0 0 100 100" width="100%" height="100%"><rect width="100" height="100" rx="24" fill="#0b3d91"/>
<rect x="18" y="30" width="64" height="44" rx="9" fill="#2f8ae0"/><rect x="58" y="44" width="24" height="16" rx="6" fill="#f5b83d"/>
<circle cx="70" cy="52" r="3" fill="#0b3d91"/></svg>"""


def logo_html() -> str:
    if LOGO.exists():
        data = base64.b64encode(LOGO.read_bytes()).decode()
        return f'<div class="logo"><img src="data:image/png;base64,{data}"></div>'
    return f'<div class="logo">{WALLET_SVG}</div>'


def text_frame_html(theme: str, kind: str) -> str:
    gradient, color = BACKGROUNDS[theme]
    sub = "#475569" if theme == "light" else "#c7d2fe"
    if kind == "intro":
        body = f"""{logo_html()}
          <div class="title">Wallet Buddy</div>
          <div class="sub">Your money, sorted.<br>Right inside Telegram.</div>"""
    else:
        pill = "#ffffff" if theme == "light" else "rgba(255,255,255,.10)"
        body = f"""<div class="title small">Free on Telegram</div>
          <div class="handle">{html.escape(BOT)}</div>
          <div class="sub low">Search it or tap the link in bio</div>"""
        body = logo_html().replace('class="logo"', 'class="logo tiny"') + body
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; margin: 0; }}
      body {{ width: 1080px; height: 1920px; overflow: hidden; background: {gradient}; color: {color};
        font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif; display: flex; flex-direction: column;
        align-items: center; justify-content: center; text-align: center; padding: 0 70px; }}
      .logo {{ width: 470px; height: 470px; border-radius: 108px; overflow: hidden; background: #061a47;
        box-shadow: 0 50px 110px rgba(30, 64, 175, .45), 0 0 0 2px rgba(255,255,255,.12); margin-bottom: 90px; }}
      .logo img {{ width: 100%; height: 100%; object-fit: cover; transform: scale(1.14) translate(1.5%, 1.5%); display: block; }}
      .logo.tiny {{ width: 250px; height: 250px; border-radius: 58px; margin-bottom: 80px; }}
      .title {{ font-size: 132px; font-weight: 800; letter-spacing: -4px; line-height: 1; margin-bottom: 56px; white-space: nowrap; }}
      .title.small {{ font-size: 112px; letter-spacing: -3px; margin-bottom: 70px; }}
      .sub {{ font-size: 62px; line-height: 1.25; font-weight: 600; color: {sub}; }}
      .sub.low {{ margin-top: 80px; font-size: 54px; }}
      .handle {{ font-size: 82px; font-weight: 800; letter-spacing: -2px; padding: 40px 58px; border-radius: 120px;
        background: {"#ffffff" if theme == "light" else "rgba(255,255,255,.10)"}; color: {"#1d4ed8" if theme == "light" else "#8ec5ff"};
        box-shadow: 0 30px 70px rgba(30, 64, 175, .28); max-width: 940px; white-space: nowrap; }}
    </style></head><body>{body}</body></html>"""


def mask_html() -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#000"><div style="width:{SCREEN_W}px;
      height:{STATUS_H + SCREEN_H}px;border-radius:76px;background:#fff"></div></body></html>"""


def clip_layers(page, theme: str, headline: str, out_dir: Path) -> tuple:
    """Three images that put a clip inside the phone: back layer, front layer, rounded-corner mask."""
    out_dir.mkdir(parents=True, exist_ok=True)
    back, front, mask = (out_dir / f"{theme}-{n}.png" for n in ("back", "front", "mask"))
    page.set_content(page_html(theme, None, headline, "bg"), wait_until="load")
    page.wait_for_timeout(100)
    page.screenshot(path=str(back))
    page.set_content(page_html(theme, None, headline, "fg"), wait_until="load")
    page.wait_for_timeout(100)
    page.screenshot(path=str(front), omit_background=True)
    page.set_viewport_size({"width": SCREEN_W, "height": STATUS_H + SCREEN_H})
    page.set_content(mask_html(), wait_until="load")
    page.screenshot(path=str(mask))
    page.set_viewport_size({"width": 1080, "height": 1920})
    return back, front, mask


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
                for kind in ("intro", "cta"):
                    page.set_content(text_frame_html(theme, kind), wait_until="load")
                    page.wait_for_timeout(200)
                    target = out_dir / f"{kind}.png"
                    page.screenshot(path=str(target))
                    made.append(target)
        finally:
            browser.close()
    return made


if __name__ == "__main__":
    files = run()
    print(f"{len(files)} frames in {OUTPUT / 'frames'}")
