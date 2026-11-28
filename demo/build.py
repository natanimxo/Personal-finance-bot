"""Regenerate every promo asset with one command:

    python demo/build.py [--currency EUR] [--today 2026-11-28] [--seed 7] [--themes light,dark] [--no-clips]

Steps: seed demo/demo.db -> start the demo web app (local only) -> screenshots -> vertical
frames -> clips -> zip. Output lands in demo/output/ and demo/promo-assets.zip.
"""
import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.server import child_env, demo_server, refuse_if_unsafe  # noqa: E402

OUTPUT = ROOT / "demo" / "output"
ARCHIVE = ROOT / "demo" / "promo-assets.zip"


def check_playwright():
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise SystemExit("Playwright isn't installed. Run:\n  pip install -r demo/requirements.txt\n"
                         "  python -m playwright install ffmpeg")


def seed(args):
    command = [sys.executable, str(ROOT / "demo" / "seed.py"), "--currency", args.currency, "--seed", str(args.seed)]
    for flag, value in (("--today", args.today), ("--scale", args.scale), ("--timezone", args.timezone)):
        if value:
            command += [flag, str(value)]
    done = subprocess.run(command, cwd=str(ROOT), env=child_env(args.today))
    if done.returncode:
        raise SystemExit("Seeding failed")


def clean_output(themes):
    """Empty the folders this script owns (inside demo/output/ only)."""
    for name in ("raw", "frames", "clips"):
        folder = OUTPUT / name
        if folder.exists():
            assert OUTPUT in folder.resolve().parents
            shutil.rmtree(folder)


def make_zip():
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(OUTPUT.rglob("*")):
            if path.is_file() and ".recording" not in path.parts:
                z.write(path, path.relative_to(OUTPUT).as_posix())
    return ARCHIVE


def main(argv=None):
    parser = argparse.ArgumentParser(description="Regenerate the promo screenshots, frames and clips.")
    parser.add_argument("--currency", default="USD", help="USD (default), EUR, KES, GBP, ...")
    parser.add_argument("--seed", type=int, default=7, help="random seed for the demo data")
    parser.add_argument("--today", help="pin the demo's 'today' (YYYY-MM-DD) so every run looks the same")
    parser.add_argument("--scale", help="multiply every amount (default: sensible for the currency)")
    parser.add_argument("--timezone", help="the demo user's timezone (default: one that fits the currency)")
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--no-clips", action="store_true", help="skip the videos (they take a few minutes)")
    args = parser.parse_args(argv)
    themes = tuple(t for t in args.themes.split(",") if t)

    refuse_if_unsafe()
    check_playwright()
    from demo import clips, frames, screens

    started = time.time()
    print("1/5 Seeding demo/demo.db ...")
    seed(args)
    clean_output(themes)
    with demo_server(args.today) as base:
        print("2/5 Screenshots ...")
        raw = screens.run(base, args.today, themes)
        print(f"    {len(raw)} screenshots")
        print("3/5 Promo frames ...")
        made = frames.run(themes)
        print(f"    {len(made)} frames")
        if args.no_clips:
            print("4/5 Clips skipped")
        else:
            print("4/5 Clips (about a minute each theme) ...")
            clip_files = clips.run(base, args.today, themes)
            print(f"    {len(clip_files)} clips")
    print("5/5 Zip ...")
    archive = make_zip()
    print(f"\nDone in {time.time() - started:.0f} s.\n  {OUTPUT}\n  {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
