from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.ingest.results import ingest_completed_results
from worldcup.ingest.sports_data import FixtureDTO, TeamDTO
from worldcup.models import Match, Team
from worldcup.models.tournament import Competition
from scripts.seed_competition import seed


def _team_dto(ext, name, tla):
    return TeamDTO(external_id=ext, name=name, country_code=tla)


def _fixture_dto(ext, status, home_ext, away_ext, home_score=None, away_score=None):
    return FixtureDTO(
        external_id=ext,
        stage="group",
        group_label="A",
        kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
        status=status,
        home_external_id=home_ext,
        away_external_id=away_ext,
        home_score=home_score,
        away_score=away_score,
    )


@pytest.fixture
def fake_client_scheduled():
    """Initial state: both matches SCHEDULED."""
    client = AsyncMock()
    client.get_teams.return_value = [
        _team_dto(759, "Brazil", "BRA"),
        _team_dto(760, "France", "FRA"),
        _team_dto(761, "Argentina", "ARG"),
        _team_dto(762, "Spain", "ESP"),
    ]
    client.get_fixtures.return_value = [
        _fixture_dto(1, "SCHEDULED", 759, 760),
        _fixture_dto(2, "SCHEDULED", 761, 762),
    ]
    return client


@pytest.fixture
def fake_client_after_brazil_match():
    """Brazil vs France finished 2-1; the other still scheduled."""
    client = AsyncMock()
    client.get_teams.return_value = [
        _team_dto(759, "Brazil", "BRA"),
        _team_dto(760, "France", "FRA"),
        _team_dto(761, "Argentina", "ARG"),
        _team_dto(762, "Spain", "ESP"),
    ]
    client.get_fixtures.return_value = [
        _fixture_dto(1, "FT", 759, 760, home_score=2, away_score=1),
        _fixture_dto(2, "SCHEDULED", 761, 762),
    ]
    return client


@pytest.mark.asyncio
async def test_ingest_completed_results_detects_newly_finished(fake_client_scheduled, fake_client_after_brazil_match):
    await init_db()
    await seed()

    # Round 1: nothing has completed yet.
    summary = await ingest_completed_results(fake_client_scheduled)
    assert summary == {"newly_completed": 0, "match_ids": []}

    # Round 2: Brazil-France flips to FT.
    summary = await ingest_completed_results(fake_client_after_brazil_match)
    assert summary["newly_completed"] == 1
    assert len(summary["match_ids"]) == 1

    async with get_session() as session:
        m = (await session.execute(
            select(Match).where(Match.external_id == 1)
        )).scalar_one()
    assert m.status == "FT"
    assert m.home_score == 2
    assert m.away_score == 1
    assert m.id in summary["match_ids"]


@pytest.mark.asyncio
async def test_ingest_completed_results_idempotent(fake_client_after_brazil_match):
    await init_db()
    await seed()

    # First call brings the match to FT.
    s1 = await ingest_completed_results(fake_client_after_brazil_match)
    assert s1["newly_completed"] == 1

    # Second call: no new transitions.
    s2 = await ingest_completed_results(fake_client_after_brazil_match)
    assert s2 == {"newly_completed": 0, "match_ids": []}
