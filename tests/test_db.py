import pytest
from sqlalchemy import text

from worldcup.config import get_settings
from worldcup.db import get_session, init_db, reset_engine_cache


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "x.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()
    reset_engine_cache()

    await init_db()
    assert db_file.exists()


@pytest.mark.asyncio
async def test_get_session_yields_usable_session():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    async with get_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
