from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from worldcap.api.app import build_app
from worldcap.db import get_session, init_db
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    Team,
    TournamentForecast,
)
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_tournament_empty_state():
    await init_db()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/tournament")
    assert r.status_code == 200
    assert "Tournament outlook" in r.text


async def _seed_three_team_snapshot():
    await init_db()
    await seed()
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=1, name="Brazil", country_code="BRA"),
            Team(external_id=2, name="France", country_code="FRA"),
            Team(external_id=3, name="Argentina", country_code="ARG"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime(2026, 5, 24, tzinfo=timezone.utc),
            snapshot_trigger="manual",
            poly_odds_hash="x",
            model_state_hash="y",
            model_version="test-v0",
        )
        session.add(snap)
        await session.flush()
        session.add_all([
            TournamentForecast(snapshot_id=snap.id, team_id=teams["Brazil"].id,
                               p_champion=0.20, p_runner_up=0.15, p_semi=0.35, p_top_group=0.55,
                               poly_p_champion=0.25, edge_vs_poly=-0.05),
            TournamentForecast(snapshot_id=snap.id, team_id=teams["France"].id,
                               p_champion=0.22, p_runner_up=0.16, p_semi=0.38, p_top_group=0.60,
                               poly_p_champion=0.16, edge_vs_poly=0.06),
            TournamentForecast(snapshot_id=snap.id, team_id=teams["Argentina"].id,
                               p_champion=0.18, p_runner_up=0.14, p_semi=0.32, p_top_group=0.50,
                               poly_p_champion=0.17, edge_vs_poly=0.01),
        ])
        await session.commit()


@pytest.mark.asyncio
async def test_tournament_sorts_by_p_champion_default():
    await _seed_three_team_snapshot()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/tournament")
    assert r.status_code == 200
    body = r.text
    # France (0.22) should appear before Brazil (0.20) in the rendered HTML
    france_pos = body.find("France")
    brazil_pos = body.find("Brazil")
    arg_pos = body.find("Argentina")
    assert france_pos != -1 and brazil_pos != -1 and arg_pos != -1
    assert france_pos < brazil_pos < arg_pos


@pytest.mark.asyncio
async def test_tournament_sorts_by_edge_when_requested():
    await _seed_three_team_snapshot()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/tournament?order_by=edge_vs_poly")
    assert r.status_code == 200
    body = r.text
    # France (+6pp) should appear first, then Argentina (+1pp), then Brazil (-5pp)
    france_pos = body.find("France")
    arg_pos = body.find("Argentina")
    brazil_pos = body.find("Brazil")
    assert france_pos < arg_pos < brazil_pos
