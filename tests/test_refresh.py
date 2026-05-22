from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db
from worldcap.ingest.sports_data import FixtureDTO, TeamDTO
from worldcap.jobs.refresh import run_refresh
from worldcap.models import ForecastSnapshot, OddsSnapshot, Team, TournamentForecast
from scripts.seed_competition import seed


@pytest.fixture
def fake_football_client():
    client = AsyncMock()
    client.get_teams.return_value = [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]
    client.get_fixtures.return_value = [
        FixtureDTO(
            external_id=1,
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


@pytest.fixture
def fake_poly_collector():
    market = MagicMock()
    market.question = "Winner of FIFA World Cup 2026"
    market.outcomes = ["Brazil", "France"]
    market.outcome_prices = [0.25, 0.18]
    market.volume = 100000.0
    result = MagicMock()
    result.status = "success"
    result.markets = [market]
    collector = MagicMock()
    collector.fetch_markets = AsyncMock(return_value=result)
    return collector


@pytest.mark.asyncio
async def test_run_refresh_end_to_end(fake_football_client, fake_poly_collector, monkeypatch):
    await init_db()
    await seed()

    snap = await run_refresh(
        trigger="manual",
        football_client=fake_football_client,
        poly_collector=fake_poly_collector,
        as_of=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert isinstance(snap, ForecastSnapshot)
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        odds = (await session.execute(select(OddsSnapshot))).scalars().all()
        forecasts = (await session.execute(select(TournamentForecast))).scalars().all()
    assert len(teams) == 2
    assert len(odds) == 1
    assert len(forecasts) == 2

    out_dir = get_settings().digest_output_dir
    assert (out_dir / "2026-05-21.md").exists()
    assert get_settings().whatsapp_pickup_path.exists()
