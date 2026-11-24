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
