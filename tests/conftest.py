import os

# Skip building the real app on module import (no credentials in tests).
os.environ["WORLDCAP_SKIP_DEFAULT_APP"] = "1"

from pathlib import Path

import pytest
import respx


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    db_path = tmp_path / "worldcap.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(output_dir / "latest.md"))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
