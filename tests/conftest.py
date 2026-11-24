"""Test settings. Environment is set before any app module is imported."""
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "1:test-token")
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


TEST_CHANNEL = -1001000000001


@pytest.fixture(autouse=True)
def gate_on_with_one_channel(request, monkeypatch):
    """Most tests are about the gate's checks: it is on, with one channel whose title
    and invite link are already cached. tests/test_gate.py uses the real database
    (the seeded rotation, off by default) instead."""
    from app.bot import membership
    from app.services import gate

    membership._not_admin_alerted.clear()
    if request.module.__name__.endswith("test_gate"):
        return
    channel = gate.Channel(TEST_CHANNEL, 1, "Test Channel", "https://t.me/+testInvite")
    monkeypatch.setattr(gate, "is_on", lambda: True)
    monkeypatch.setattr(gate, "channels", lambda now=None: [channel])
