"""Test settings. Environment is set before any app module is imported."""
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "1:test-token")
os.environ.setdefault("CHANNEL_ID", "@test_channel")
os.environ.setdefault("CHANNEL_LINK", "https://t.me/test_channel_name")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "session.db"))
for var in ("RAILWAY_VOLUME_MOUNT_PATH", "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID"):
    os.environ.pop(var, None)

import pytest  # noqa: E402

from app import config  # noqa: E402


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the app at an empty database file in a temp folder."""
    path = tmp_path / "sub" / "expenses.db"
    monkeypatch.setattr(config, "DB_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def reset_process_caches():
    """The membership cache and the known-active set live for the whole process;
    every test starts with both empty."""
    from app.bot import membership
    from app.bot.errors import throttle

    membership.membership_cache.clear()
    membership._known_active.clear()
    throttle.last, throttle.suppressed = None, 0
    yield


@pytest.fixture(autouse=True)
def gate_on_without_free_month(monkeypatch):
    """Most tests are about the gate's checks, so it is on and the free month is off;
    tests/test_gate.py covers the real defaults (off, 30 free days, rotation)."""
    from app.services import gate

    monkeypatch.setattr(config, "GATE_ENABLED", True)
    monkeypatch.setattr(config, "GATE_CHANNELS", "")
    monkeypatch.setattr(gate, "FREE_DAYS", 0)
    from app.bot import membership
    membership._not_admin_alerted.clear()
    membership._titles.clear()
