from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from worldcup.api.app import build_app
from worldcup.db import get_session, init_db
from worldcup.models import (
    Competition,
    ForecastSnapshot,
    Match,
    Team,
    TournamentForecast,
)
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_home_empty_state():
    await init_db()

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "world cup" in r.text.lower()
    assert "Refresh now" in r.text


@pytest.mark.asyncio
async def test_home_shows_contenders_and_next_matches():
    await init_db()
    await seed()

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime(2026, 5, 24, tzinfo=timezone.utc),
            snapshot_trigger="manual",
            poly_odds_hash="abc",
            model_state_hash="def",
            model_version="test-v0",
        )
        session.add(snap)
        await session.flush()
        session.add_all([
            TournamentForecast(snapshot_id=snap.id, team_id=teams["Brazil"].id,
                               p_champion=0.22, poly_p_champion=0.25, edge_vs_poly=-0.03),
            TournamentForecast(snapshot_id=snap.id, team_id=teams["France"].id,
                               p_champion=0.18, poly_p_champion=0.16, edge_vs_poly=0.02),
        ])
        session.add(Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=datetime.now(timezone.utc) + timedelta(days=3),
            status="SCHEDULED",
        ))
        await session.commit()

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "Brazil" in r.text
    assert "France" in r.text
    assert "Brazil vs France" in r.text
    assert "22.0%" in r.text or "22%" in r.text
