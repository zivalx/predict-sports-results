import os

# Skip building the real app on module import (no credentials in tests).
os.environ["WORLDCUP_SKIP_DEFAULT_APP"] = "1"

from pathlib import Path

import pytest
import respx


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    db_path = tmp_path / "worldcup.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(output_dir / "latest.md"))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GNEWS_API_KEY", "")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test/0.1")
    monkeypatch.setenv("RATIONALE_TOKEN_BUDGET", "100000")
    monkeypatch.setenv("SENTIMENT_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("RATIONALE_MODEL", "claude-sonnet-4-5")
    # Reset caches so the new env vars take effect
    from worldcup.config import get_settings
    from worldcup.db import reset_engine_cache
    get_settings.cache_clear()
    reset_engine_cache()
    yield


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
