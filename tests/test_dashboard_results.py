"""Tests for the /results page (completed matches + retro forecast comparison)."""
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
    Team,
)
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_results_empty_state():
    """No FT matches → friendly empty state, not a crash."""
    await init_db()
    await seed()

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/results")
    assert r.status_code == 200
    assert "No completed matches yet" in r.text


@pytest.mark.asyncio
async def test_results_shows_completed_matches_with_retro():
    """Seed a FT match + a MatchForecast that predicted the wrong outcome.
    Results page should render the match + show '✗ We forecast X' style retro line."""
    await init_db()
    await seed()

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=801, name="Brazil", country_code="BRA"),
            Team(external_id=802, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}

        match = Match(
            external_id=501,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="FT",
            home_score=0,
            away_score=1,  # France won; our forecast predicted Brazil (home win)
        )
        session.add(match)

        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime(2026, 6, 10, tzinfo=timezone.utc),
            snapshot_trigger="manual",
            poly_odds_hash="rr1",
            model_state_hash="rr2",
            model_version="test-v0",
        )
        session.add(snap)
        await session.flush()

        # Our model heavily favoured Brazil (home win) — but France won
        session.add(MatchForecast(
            snapshot_id=snap.id,
            match_id=match.id,
            p_home=0.62,   # predicted Brazil to win
            p_draw=0.22,
            p_away=0.16,
            edge_vs_poly=0.0,
        ))
        await session.commit()

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/results")

    assert r.status_code == 200
    body = r.text
    # Match card is present
    assert "Brazil" in body
    assert "France" in body
    # Score shown
    assert "0" in body and "1" in body
    # Wrong prediction indicated
    assert "✗" in body
    assert "62%" in body or "62" in body
