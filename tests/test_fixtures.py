from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.ingest.fixtures import ingest_teams_and_fixtures
from worldcup.ingest.sports_data import FixtureDTO, TeamDTO
from worldcup.models import Match, Team
from scripts.seed_competition import seed


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.get_teams.return_value = [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]
    client.get_fixtures.return_value = [
        FixtureDTO(
            external_id=1001,
            stage="group",
            group_label="A",
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
            home_external_id=759,
            away_external_id=760,
            home_score=None,
            away_score=None,
        )
    ]
    return client


@pytest.mark.asyncio
async def test_ingest_creates_rows(fake_client):
    await init_db()
    await seed()

    summary = await ingest_teams_and_fixtures(fake_client)

    assert summary == {"teams_upserted": 2, "matches_upserted": 1}
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        matches = (await session.execute(select(Match))).scalars().all()
    assert len(teams) == 2
    assert len(matches) == 1
    assert matches[0].home_team_id is not None
    assert matches[0].away_team_id is not None


@pytest.mark.asyncio
async def test_ingest_is_idempotent(fake_client):
    await init_db()
    await seed()

    await ingest_teams_and_fixtures(fake_client)
    await ingest_teams_and_fixtures(fake_client)

    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        matches = (await session.execute(select(Match))).scalars().all()
    assert len(teams) == 2
    assert len(matches) == 1
