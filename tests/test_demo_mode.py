"""Demo mode (promo screenshots and clips): local only, its own database, one demo user,
refuses to start next to production, and seeds believable data."""
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.services import periods
from app.web import demo as demo_web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from demo import seed  # noqa: E402


def run_config(extra: dict, drop=()):
    """`import app.config` in a fresh process with demo mode on and these variables."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RAILWAY_", "DEMO_")) and k not in drop}
    env.update(DEMO_MODE="true", BOT_TOKEN="123:real-looking-token", WEBHOOK_SECRET="s" * 32, **extra)
    return subprocess.run(
        [sys.executable, "-c", "from app import config; "
         "print(config.DB_PATH, '|', repr(config.BOT_TOKEN), '|', config.ADMIN_CHAT_ID, '|', repr(config.PUBLIC_URL))"],
        cwd=str(ROOT), env=env, capture_output=True, text=True)


# --- the safety guard -------------------------------------------------------------------------
@pytest.mark.parametrize("environ,fragment", [
    ({"RAILWAY_ENVIRONMENT": "production"}, "RAILWAY_ENVIRONMENT"),
    ({"RAILWAY_VOLUME_MOUNT_PATH": "/data"}, "RAILWAY_VOLUME_MOUNT_PATH"),
    ({"RAILWAY_PUBLIC_DOMAIN": "x.up.railway.app", "PATH": "/bin"}, "RAILWAY_PUBLIC_DOMAIN"),
    ({"DB_PATH": "/data/expenses.db"}, "/data/expenses.db"),
    ({"DB_PATH": "/data"}, "/data"),
    ({"DB_PATH": "\\data\\expenses.db"}, "production volume"),
])
def test_demo_refuses_near_production(environ, fragment):
    assert fragment in "; ".join(config.demo_problems(environ))


@pytest.mark.parametrize("environ", [{}, {"DB_PATH": "./data/expenses.db"}, {"DB_PATH": "C:/stuff/data/x.db"}, {"BOT_TOKEN": "1:x"}])
def test_demo_allows_a_clean_environment(environ):
    assert config.demo_problems(environ) == []


@pytest.mark.parametrize("extra", [{"RAILWAY_ENVIRONMENT": "production"}, {"RAILWAY_PROJECT_ID": "abc"},
                                   {"DB_PATH": "/data/expenses.db"}])
def test_the_app_will_not_start_in_demo_mode_near_production(extra):
    done = run_config(extra)
    assert done.returncode != 0 and "DEMO_MODE refuses to start" in (done.stderr + done.stdout)
    assert "Nothing was touched" in (done.stderr + done.stdout)


def test_demo_mode_uses_its_own_database_and_ignores_real_settings():
    done = run_config({"DB_PATH": "./data/real.db", "ADMIN_CHAT_ID": "796002786", "PUBLIC_URL": "https://real.example"})
    assert done.returncode == 0, done.stderr
    db, token, admin, url = [part.strip() for part in done.stdout.split("|")]
    assert db.replace("\\", "/").endswith("demo/demo.db") and "real.db" not in db
    assert (token, admin, url) == ("''", "None", "''")      # a demo never loads a real token or admin


def test_demo_mode_is_off_by_default():
    assert config.DEMO_MODE is False and not config.DB_PATH.replace("\\", "/").endswith("demo/demo.db")


# --- the demo web app ---------------------------------------------------------------------------
@pytest.fixture
def demo_client(fresh_db, monkeypatch):
    from app.services import gate
    from app.web.server import create_app

    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(config, "BOT_TOKEN", "")
    monkeypatch.setattr(config, "DEMO_TODAY", "")
    with TestClient(create_app()) as client:
        gate.set_on(True)                      # even with the gate on, the demo user is never checked
        yield client


def test_the_demo_user_needs_no_sign_in_and_no_channel(demo_client):
    r = demo_client.get("/api/me")             # no Authorization header at all
    assert r.status_code == 200 and r.json()["user"]["id"] == config.DEMO_USER_ID


def test_nothing_can_be_sent_to_telegram(demo_client):
    import asyncio

    application = demo_client.app.state.application
    assert isinstance(application, demo_web.DemoApplication)
    assert asyncio.run(application.bot.send_message(chat_id=1, text="x")) is None
    assert asyncio.run(application.bot.send_document(chat_id=1, document=b"x")) is None
    assert demo_client.post("/telegram/webhook", json={}).status_code in (404, 405)   # no webhook in demo mode
    assert demo_client.get("/healthz").json() == {"ok": True, "demo": True}
    assert demo_client.app.state.mode == "demo"


def test_the_page_loads_the_demo_telegram_script_not_telegrams(demo_client):
    page = demo_client.get("/").text
    assert '<script src="/demo-telegram.js"></script>' in page and "telegram.org" not in page
    assert 'src="app.js"' in page


def test_theme_palettes_match_what_the_app_reads(demo_client):
    script = demo_client.get("/demo-telegram.js").text
    assert "--tg-theme-" in script and 'get("theme") === "dark"' in script
    for scheme in ("light", "dark"):
        assert set(demo_web.PALETTES[scheme]) >= {
            "bg_color", "text_color", "hint_color", "link_color", "button_color", "button_text_color",
            "secondary_bg_color", "section_bg_color", "section_header_text_color", "destructive_text_color"}
    assert demo_web.PALETTES["light"]["bg_color"] == "#ffffff" and demo_web.PALETTES["dark"]["secondary_bg_color"] == "#000000"
    # the app treats this as Telegram: initData and a platform are present, and the buttons exist
    for needle in ('platform: "ios"', 'initData: "demo"', "MainButton: main", "BackButton: back", "HapticFeedback"):
        assert needle in script
    # every Telegram API the app calls is in the stub
    app_js = (ROOT / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    import re
    for name in set(re.findall(r"tg\.(MainButton|BackButton|HapticFeedback)\.(\w+)", app_js)):
        assert name[1] in script, name


def test_create_demo_app_only_in_demo_mode():
    with pytest.raises(RuntimeError):
        demo_web.create_demo_app()


def test_the_pinned_clock(monkeypatch):
    monkeypatch.setattr(periods, "FROZEN_NOW", None)
    periods.freeze("2026-11-28")
    try:
        with periods.use_zone("Africa/Nairobi"):
            assert periods.today() == date(2026, 11, 28)
        with periods.use_zone("America/New_York"):
            assert periods.today() == date(2026, 11, 28)          # the same day from New York to Nairobi
    finally:
        periods.freeze(None)
    assert periods.FROZEN_NOW is None


# --- the seed ----------------------------------------------------------------------------------------
NOV_28 = date(2026, 11, 28)


def collect(db_path, **kwargs):
    """Seed `db_path` and read back everything the tests look at."""
    from app.db import get_conn
    from app.services import accounts, budgets, transactions

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "DB_PATH", str(db_path))
        summary = seed.build(**kwargs)
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT type, category, account, to_account, amount_minor, note, occurred_at FROM expenses ORDER BY id")]
        data = {"summary": summary, "rows": rows,
                "balances": {a["account"]: a["balance_minor"] for a in accounts.overview(config.DEMO_USER_ID)},
                "budgets": {b["category"]: b for b in budgets.overview(config.DEMO_USER_ID)},
                "labels": [a["label"] for a in accounts.overview(config.DEMO_USER_ID)]}
        data["entries"] = [(r["type"], r["category"], r["account"], r["amount_minor"], r["note"], r["occurred_at"])
                           for r in rows]
        return data


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    base = tmp_path_factory.mktemp("demo")
    first = collect(base / "a.db", today=NOV_28)
    second = collect(base / "b.db", today=NOV_28)
    kenya = collect(base / "c.db", today=date(2026, 12, 3), currency="KES")
    return {"usd": first, "again": second, "kes": kenya}


def day_of(row):
    return date.fromisoformat(row["occurred_at"][:10])


def test_the_seed_is_the_same_every_time(seeded):
    assert seeded["usd"]["entries"] == seeded["again"]["entries"] and len(seeded["usd"]["entries"]) > 150
    assert seeded["usd"]["summary"] == seeded["again"]["summary"]


def test_about_three_months_of_believable_notes(seeded):
    rows = seeded["usd"]["rows"]
    days = [day_of(r) for r in rows]
    assert 75 <= (max(days) - min(days)).days <= 110
    notes = {r["note"] for r in rows}
    assert {"Lunch with Sam", "Uber home", "Netflix", "Weekly groceries", "Rent", "Monthly salary"} <= notes
    groceries = [day_of(r) for r in rows if r["note"] == "Weekly groceries"]
    assert sum(d.weekday() == 5 for d in groceries) / len(groceries) >= 0.8       # on Saturdays
    coffee = [day_of(r) for r in rows if r["note"] in ("Morning coffee", "Flat white", "Coffee with a colleague")]
    assert coffee and all(d.weekday() < 5 for d in coffee)                       # on workdays
    assert {r["type"] for r in rows} == {"income", "expense", "transfer"}


def test_salary_rent_freelance_and_one_gift(seeded):
    rows = seeded["usd"]["rows"]
    firsts = {day_of(r) for r in rows if r["note"] == "Monthly salary"}
    assert firsts and all(d.day == 1 for d in firsts)
    assert {r["amount_minor"] for r in rows if r["note"] == "Monthly salary"} == {320000}
    rents = [r for r in rows if r["note"] == "Rent"]
    assert {r["amount_minor"] for r in rents} == {110000} and all(day_of(r).day == 1 for r in rents)
    assert len(rents) == len(firsts)
    freelance = [r["amount_minor"] for r in rows if r["category"] == "freelance"]
    assert len(freelance) >= 4 and all(25000 <= a <= 60000 for a in freelance)
    assert len([r for r in rows if r["category"] == "gift"]) == 1


def test_every_month_ends_positive_with_a_savings_rate_of_about_a_fifth(seeded):
    months = seeded["usd"]["summary"]["months"]
    assert len(months) >= 3
    *complete, current = months.values()
    for month in complete:
        assert 0.17 <= month["savings_rate"] <= 0.26, month
    assert 0.18 <= current["savings_rate"] <= 0.27                               # 28 Nov: nearly a full month


def test_budgets_food_70_shopping_95_transport_40(seeded):
    used = seeded["usd"]["summary"]["budget_percent"]           # measured while "today" was pinned
    assert 65 <= used["food"] <= 75
    assert 94 <= used["shopping"] <= 98                                  # about 96%: the warning banner shows
    assert 35 <= used["transport"] <= 45
    assert set(seeded["usd"]["budgets"]) >= {"food", "shopping", "transport"}


def test_budget_limits_are_round_numbers(seeded):
    limits = {c: b["limit_minor"] // 100 for c, b in seeded["usd"]["budgets"].items() if b["limit_minor"]}
    assert limits == {"food": 1500, "transport": 750, "shopping": 225}


def test_accounts_have_sensible_balances(seeded):
    balances = seeded["usd"]["balances"]
    assert seeded["usd"]["labels"] == ["💵 Cash", "🏦 Bank", "💳 Card", "📱 Mobile Wallet"]
    assert balances["cash"] >= 0 and balances["mobile_money"] >= 0
    assert balances["bank"] > 100000                                             # savings built up over the months
    assert -60000 <= balances["card"] <= 0                                      # this week's card spending, paid off weekly
    assert seeded["usd"]["summary"]["currency"] == "USD"


def test_another_currency_scales_amounts_and_timezone(seeded):
    kes = seeded["kes"]
    assert (kes["summary"]["currency"], kes["summary"]["timezone"]) == ("KES", "Africa/Nairobi")
    salary = {r["amount_minor"] for r in kes["rows"] if r["note"] == "Monthly salary"}
    assert salary == {416000 * 100}                                              # 3,200 x 130
    assert all(r["amount_minor"] % 1000 == 0 for r in kes["rows"])               # whole tens, no cents
    # run on the 3rd of a month: this month has little in it, but nothing breaks and budgets still hold
    used = kes["summary"]["budget_percent"]
    assert 60 <= used["food"] <= 80 and used["shopping"] >= 90 and 33 <= used["transport"] <= 47
    assert kes["summary"]["months"]["2026-12"]["savings_rate"] > 0


def test_the_seed_refuses_near_production_and_touches_nothing(tmp_path, monkeypatch):
    target = tmp_path / "keep.db"
    target.write_text("precious")
    monkeypatch.setattr(config, "DB_PATH", str(target))
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "prod")
    with pytest.raises(SystemExit, match="RAILWAY_PROJECT_ID"):
        seed.build(NOV_28)
    monkeypatch.delenv("RAILWAY_PROJECT_ID")
    monkeypatch.setattr(config, "DB_PATH", "/data/expenses.db")
    with pytest.raises(SystemExit, match="/data"):
        seed.build(NOV_28)
    assert target.read_text() == "precious"


def test_demo_output_and_database_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for line in ("demo/demo.db", "demo/output/", "demo/promo-assets.zip"):
        assert line in ignored.splitlines()


def test_the_demo_has_one_command_and_a_readme():
    text = (ROOT / "demo" / "README.md").read_text(encoding="utf-8")
    assert "python demo/build.py" in text and "refuses to start" in text
    for name in ("seed.py", "screens.py", "frames.py", "clips.py", "build.py", "server.py", "requirements.txt"):
        assert (ROOT / "demo" / name).exists(), name


# --- what the promo asks of the app and the frames ---------------------------------------------------
STATIC = ROOT / "app" / "web" / "static"


def test_the_app_warns_when_a_budget_is_at_80_percent_or_more():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function budgetBanner" in js and ">= 0.8" in js
    assert "You've used ${pct}% of your ${name} budget" in js
    assert js.count("budgetBanner(") >= 3                                  # defined, Home and Budgets
    assert ".banner" in (STATIC / "styles.css").read_text(encoding="utf-8")


def test_empty_date_filters_show_from_and_to():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'class: "date-placeholder"' in js and 'label.replace(" date", "")' in js
    assert "-webkit-datetime-edit" in css


def test_the_frames_have_the_new_headline_and_the_intro_and_cta_frames():
    from demo import frames
    heads = {name: head for name, _, head in frames.FRAMES}
    assert heads["transactions"] == "Find any transaction fast"
    intro, cta = (frames.text_frame_html("light", k) for k in ("intro", "cta"))
    assert "Wallet Buddy" in intro and "Your money, sorted." in intro and "Right inside Telegram." in intro
    assert "Free on Telegram" in cta and "@Wallet_buddy_bot" in cta and "Search it or tap the link in bio" in cta
    assert (ROOT / "demo" / "assets" / "logo.png").exists()


def test_clips_are_mp4_h264_in_two_sizes():
    from demo import clips
    assert clips.VIDEO_SCALE == 2 and set(clips.HEADLINES) == set(clips.CLIPS)
    source = (ROOT / "demo" / "clips.py").read_text(encoding="utf-8")
    assert "libx264" in source and ".mp4" in source and "framed" in source and "raw" in source
