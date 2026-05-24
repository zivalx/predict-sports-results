from pathlib import Path

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.model.elo import INITIAL_RATING
from worldcup.model.ratings import load_seed_ratings
from worldcup.models import Team, TeamRating
from scripts.seed_competition import seed


@pytest.fixture
def seed_csv(tmp_path: Path) -> Path:
    p = tmp_path / "ratings.csv"
    p.write_text("country_code,rating\nBRA,1790\nFRA,1830\n")
    return p


@pytest.mark.asyncio
async def test_load_seed_ratings_upserts_for_known_codes(seed_csv):
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
            Team(external_id=761, name="Unknownia", country_code="XXX"),
        ])
        await session.commit()

    summary = await load_seed_ratings(path=seed_csv)
    assert summary["inserted"] == 3
    assert summary["defaulted"] == 1  # XXX is not in the CSV

    async with get_session() as session:
        rows = (await session.execute(select(TeamRating))).scalars().all()
    by_team_external = {}
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
    team_by_id = {t.id: t for t in teams}
    for r in rows:
        by_team_external[team_by_id[r.team_id].country_code] = r.rating

    assert by_team_external["BRA"] == 1790.0
    assert by_team_external["FRA"] == 1830.0
    assert by_team_external["XXX"] == INITIAL_RATING


@pytest.mark.asyncio
async def test_load_seed_ratings_is_idempotent(seed_csv):
    await init_db()
    await seed()

    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.commit()

    s1 = await load_seed_ratings(path=seed_csv)
    s2 = await load_seed_ratings(path=seed_csv)
    assert s1["inserted"] == 1
    assert s2["inserted"] == 0
    assert s2["skipped_existing"] == 1

    async with get_session() as session:
        rows = (await session.execute(select(TeamRating))).scalars().all()
    assert len(rows) == 1
