from datetime import datetime, timezone
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
    MatchForecast,
    NewsItem,
    Player,
    SentimentScore,
    Team,
    TeamRating,
    TopScorerForecast,
    TournamentForecast,
)
from scripts.seed_competition import seed


async def _seed_full():
    """Seed competition, 2 teams, ratings, sentiment, a match with forecast + rationale,
    one player + top-scorer forecast."""
    await init_db()
    await seed()
    as_of = datetime(2026, 5, 24, tzinfo=timezone.utc)
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=1, name="Brazil", country_code="BRA"),
            Team(external_id=2, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add_all([
            TeamRating(team_id=teams["Brazil"].id, rating=1790.0, last_updated=as_of, source="seed"),
            TeamRating(team_id=teams["France"].id, rating=1830.0, last_updated=as_of, source="seed"),
        ])
        session.add(SentimentScore(
            target_type="team", target_id=teams["Brazil"].id, ts=as_of,
            score=-0.1, confidence=0.8, model_version="team-rollup-v0",
        ))
        session.add(NewsItem(
            competition_id=comp.id, team_id=teams["Brazil"].id,
            source="gnews", url="https://news/1", ts=as_of,
            title="Vinicius doubtful",
        ))
        match = Match(
            external_id=1, competition_id=comp.id, stage="group", group_label="G",
            home_team_id=teams["Brazil"].id, away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        )
        session.add(match)
        snap = ForecastSnapshot(
            competition_id=comp.id, snapshot_date=as_of,
            snapshot_trigger="manual", poly_odds_hash="x", model_state_hash="y",
            model_version="test",
        )
        session.add(snap)
        await session.flush()
        session.add_all([
            TournamentForecast(snapshot_id=snap.id, team_id=teams["Brazil"].id,
                               p_champion=0.20, p_runner_up=0.10, p_semi=0.30, p_top_group=0.55,
                               poly_p_champion=0.22, edge_vs_poly=-0.02),
            TournamentForecast(snapshot_id=snap.id, team_id=teams["France"].id,
                               p_champion=0.22, p_runner_up=0.12, p_semi=0.34, p_top_group=0.60,
                               poly_p_champion=0.18, edge_vs_poly=0.04),
        ])
        session.add(MatchForecast(
            snapshot_id=snap.id, match_id=match.id,
            p_home=0.40, p_draw=0.28, p_away=0.32,
            p_home_poly=0.45, p_draw_poly=0.27, p_away_poly=0.28,
            edge_vs_poly=-0.05,
            rationale_md="Brazil are slightly underrated.",
        ))
        # one player
        session.add(Player(name="Vinicius", team_id=teams["Brazil"].id, goals_per_90=0.7))
        await session.flush()
        players = {p.name: p for p in (await session.execute(select(Player))).scalars().all()}
        session.add(TopScorerForecast(
            snapshot_id=snap.id, player_id=players["Vinicius"].id,
            p_golden_boot=0.14, expected_goals=3.1,
            poly_p_top_scorer=0.16, edge_vs_poly=-0.02,
        ))
        await session.commit()


@pytest.mark.asyncio
async def test_tournament_outlook_endpoint():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/tournament_outlook?top_n=5")
    assert r.status_code == 200
    body = r.json()
    assert "snapshot_date" in body
    assert len(body["entries"]) == 2
    # Sorted by p_champion desc → France first
    assert body["entries"][0]["team"] == "France"


@pytest.mark.asyncio
async def test_match_forecast_endpoint():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/match_forecast?home_team=Brazil&away_team=France")
    assert r.status_code == 200
    body = r.json()
    assert body["home_team"] == "Brazil"
    assert body["away_team"] == "France"
    assert body["p_home"] == 0.40
    assert "Vinicius doubtful" in body["home_recent_headlines"]
    assert "underrated" in (body["rationale_md"] or "")


@pytest.mark.asyncio
async def test_match_forecast_unknown_team_returns_404():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/match_forecast?home_team=Atlantis&away_team=France")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_golden_boot_race_endpoint():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/golden_boot_race?top_n=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["player"] == "Vinicius"
    assert body["entries"][0]["p_golden_boot"] == 0.14


@pytest.mark.asyncio
async def test_team_overview_endpoint():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/team_overview?team_name=Brazil")
    assert r.status_code == 200
    body = r.json()
    assert body["team"] == "Brazil"
    assert body["elo_rating"] == 1790.0
    assert body["p_champion"] == 0.20
    assert body["sentiment"] == -0.1
    assert "Vinicius doubtful" in body["recent_headlines"]
    assert any("Brazil vs France" in m for m in body["upcoming_matches"])


@pytest.mark.asyncio
async def test_team_overview_unknown_team_returns_404():
    await _seed_full()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/team_overview?team_name=Atlantis")
    assert r.status_code == 404
