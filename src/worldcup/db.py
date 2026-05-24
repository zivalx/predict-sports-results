from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from worldcup.config import get_settings


@lru_cache
def create_engine_():
    return create_async_engine(get_settings().database_url, future=True, echo=False)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_engine_(), class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables from SQLModel metadata. Alembic migrations are authoritative;
    this exists for tests."""
    engine = create_engine_()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_session():
    async with _sessionmaker()() as session:
        yield session


def reset_engine_cache() -> None:
    """Called by tests when DATABASE_URL changes mid-process."""
    create_engine_.cache_clear()
    _sessionmaker.cache_clear()
