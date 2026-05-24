from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.model.naive import generate_naive_forecast
from worldcup.models import ForecastSnapshot, OddsSnapshot, Team, TournamentForecast
from worldcup.models.tournament import Competition
from scripts.seed_competition import seed


async def _team_by_name(name: str) -> Team:
    async with get_session() as session:
        return (await session.execute(select(Team).where(Team.name == name))).scalar_one()


@pytest.mark.asyncio
async def test_naive_forecast_uses_latest_outright_snapshot():
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
            Team(external_id=761, name="Argentina", country_code="ARG"),
        ])
        await session.flush()

        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "France": 0.18, "Argentina": 0.17},
            volume=100000.0,
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")

    async with get_session() as session:
        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()

    assert len(forecasts) == 3
    by_team = {f.team_id: f for f in forecasts}
    brazil = await _team_by_name("Brazil")
    assert pytest.approx(by_team[brazil.id].p_champion, rel=1e-6) == 0.25
    assert by_team[brazil.id].edge_vs_poly == 0.0
    assert snap.model_version == "naive-poly-only-v0"


@pytest.mark.asyncio
async def test_naive_forecast_skips_unknown_team_names():
    await init_db()
    await seed()

    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.flush()

        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "Eldorado": 0.05},
            volume=None,
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")

    async with get_session() as session:
        rows = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(rows) == 1
