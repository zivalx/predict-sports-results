from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db
from worldcap.ingest.sports_data import FixtureDTO, TeamDTO
from worldcap.jobs.refresh import run_refresh
from worldcap.models import (
    ForecastSnapshot,
    MatchForecast,
    OddsSnapshot,
    Team,
    TournamentForecast,
)
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
async def test_run_refresh_end_to_end(fake_football_client, fake_poly_collector):
    await init_db()
    await seed()

    # Use an as_of close to the fixture kickoff (default horizon is 14 days; the
    # fixture is set for 2026-06-11, so we put as_of at 2026-06-05).
    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)
    snap = await run_refresh(
        trigger="manual",
        football_client=fake_football_client,
        poly_collector=fake_poly_collector,
        as_of=as_of,
    )

    assert isinstance(snap, ForecastSnapshot)
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        odds = (await session.execute(select(OddsSnapshot))).scalars().all()
        tournament_forecasts = (await session.execute(select(TournamentForecast))).scalars().all()
        match_forecasts = (await session.execute(select(MatchForecast))).scalars().all()
    assert len(teams) == 2
    assert len(odds) == 1
    assert len(tournament_forecasts) == 0  # simulator skips when WC groups not fully seeded
    assert len(match_forecasts) == 1       # Brazil vs France within horizon

    mf = match_forecasts[0]
    assert mf.p_home + mf.p_draw + mf.p_away == pytest.approx(1.0, abs=1e-9)
    assert mf.model_version == "elo-v0"

    out_dir = get_settings().digest_output_dir
    assert (out_dir / "2026-06-05.md").exists()
    assert get_settings().whatsapp_pickup_path.exists()
