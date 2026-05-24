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
    Match,
    MatchForecast,
    NewsItem,
    Team,
)
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_match_detail_returns_404_when_missing():
    await init_db()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/match/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_match_detail_renders_with_forecast_and_headlines():
    await init_db()
    await seed()
    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=1, name="Brazil", country_code="BRA"),
            Team(external_id=2, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        match = Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="G",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        )
        session.add(match)
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=as_of,
            snapshot_trigger="manual",
            poly_odds_hash="x",
            model_state_hash="y",
            model_version="test",
        )
        session.add(snap)
        await session.flush()
        session.add(MatchForecast(
            snapshot_id=snap.id,
            match_id=match.id,
            p_home=0.40, p_draw=0.28, p_away=0.32,
            p_home_poly=0.45, p_draw_poly=0.27, p_away_poly=0.28,
            edge_vs_poly=-0.05,
            rationale_md="Brazil are slightly underrated by the market.",
        ))
        session.add_all([
            NewsItem(
                competition_id=comp.id, team_id=teams["Brazil"].id,
                source="gnews", url="https://news/b1", ts=as_of,
                title="Vinicius doubtful for Brazil",
            ),
            NewsItem(
                competition_id=comp.id, team_id=teams["France"].id,
                source="gnews", url="https://news/f1", ts=as_of,
                title="Mbappe quotes from camp",
            ),
        ])
        await session.commit()
        await session.refresh(match)
        match_id = match.id

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/match/{match_id}")
    assert r.status_code == 200
    body = r.text
    assert "Brazil vs France" in body
    assert "Group G" in body
    assert "40.0%" in body or "40%" in body
    assert "Brazil are slightly underrated" in body
    assert "Vinicius doubtful" in body
    assert "Mbappe quotes" in body
