"""Phase 5: local development with a .env file."""
import json
import os
from pathlib import Path

from app.config import load_dotenv

REPO = Path(__file__).resolve().parent.parent


def test_dotenv_fills_only_missing_variables(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nPF_A=one\nPF_B = "two words"\nPF_C=\nPF_SET=from-file\nnot a line\n', encoding="utf-8")
    monkeypatch.setenv("PF_SET", "real")
    for key in ("PF_A", "PF_B", "PF_C"):
        monkeypatch.delenv(key, raising=False)
    load_dotenv(str(env))
    assert os.environ["PF_A"] == "one" and os.environ["PF_B"] == "two words"
    assert "PF_C" not in os.environ                    # empty values are skipped
    assert os.environ["PF_SET"] == "real"               # real environment wins
    for key in ("PF_A", "PF_B"):
        monkeypatch.delenv(key, raising=False)


def test_missing_dotenv_is_fine(tmp_path):
    load_dotenv(str(tmp_path / "nope.env"))


def test_railway_config_matches_the_plan():
    cfg = json.loads((REPO / "railway.json").read_text(encoding="utf-8"))
    assert cfg["deploy"]["healthcheckPath"] == "/healthz"
    assert cfg["deploy"]["numReplicas"] == 1             # SQLite: exactly one replica
    assert cfg["build"]["builder"] == "DOCKERFILE"


def test_every_variable_is_in_env_example():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for var in ("BOT_TOKEN", "CHANNEL_ID", "CHANNEL_LINK", "DB_PATH", "PUBLIC_URL", "WEBHOOK_SECRET", "APP_TIMEZONE",
                "DEFAULT_CURRENCY", "DEFAULT_ACCOUNTS", "ADMIN_CHAT_ID", "USE_POLLING", "PORT"):
        assert f"\n{var}=" in example or example.startswith(f"{var}="), var
