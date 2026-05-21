import asyncio
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Each test gets its own SQLite file and output dir."""
    db_path = tmp_path / "worldcap.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(output_dir / "latest.md"))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield
