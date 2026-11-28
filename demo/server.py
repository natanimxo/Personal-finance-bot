"""Start and stop the demo web app (local only), and the shared Playwright helpers."""
import os
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8800


def refuse_if_unsafe():
    """The same checks the app makes itself (app/config.py), so you get a clear message first."""
    from app import config

    problems = config.demo_problems(os.environ)
    if problems:
        raise SystemExit("The demo refuses to run: " + "; ".join(problems) + ". Nothing was touched.")


def child_env(today: str = None, port: int = PORT) -> dict:
    env = dict(os.environ, DEMO_MODE="true", DEMO_PORT=str(port), PYTHONIOENCODING="utf-8")
    env.pop("DB_PATH", None)             # demo mode ignores it anyway
    env.pop("BOT_TOKEN", None)           # and never needs a token
    if today:
        env["DEMO_TODAY"] = today
    return env


@contextmanager
def demo_server(today: str = None, port: int = PORT):
    """`python -m app.main` in demo mode: the web app only, on 127.0.0.1, on demo/demo.db."""
    refuse_if_unsafe()
    process = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=str(ROOT), env=child_env(today, port),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise SystemExit("The demo server stopped: " + (process.stdout.read() or "")[-800:])
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                    if b'"demo"' in r.read():
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The demo server didn't start in time")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def launch_browser(playwright):
    """Your installed Chrome, else Edge, else Playwright's own Chromium."""
    last = None
    for channel in ("chrome", "msedge", None):
        try:
            return playwright.chromium.launch(channel=channel) if channel else playwright.chromium.launch()
        except Exception as e:   # not installed
            last = e
    raise SystemExit(f"No browser found ({last}). Install Chrome, or run: python -m playwright install chromium")


def get_json(base: str, path: str):
    import json
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read())
