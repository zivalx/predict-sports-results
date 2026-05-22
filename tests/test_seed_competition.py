import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.models import Competition, TournamentFormat
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_seed_inserts_competition_and_format():
    await init_db()

    await seed()

    async with get_session() as session:
        comps = (await session.execute(select(Competition))).scalars().all()
        formats = (await session.execute(select(TournamentFormat))).scalars().all()

    assert len(comps) == 1
    assert comps[0].code == "WC2026"
    assert len(formats) == 1
    assert formats[0].groups_n == 12
    assert formats[0].group_size == 4
    assert formats[0].knockout_size == 32


@pytest.mark.asyncio
async def test_seed_is_idempotent():
    await init_db()

    await seed()
    await seed()

    async with get_session() as session:
        comps = (await session.execute(select(Competition))).scalars().all()
    assert len(comps) == 1
