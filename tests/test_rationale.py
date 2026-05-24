from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.enrich.claude_client import FakeClaudeClient
from worldcup.models import (
    ForecastSnapshot,
    MatchForecast,
    NewsItem,
    SentimentScore,
    Team,
    TeamRating,
)
from worldcup.models.tournament import Competition, Match
from worldcup.rationale.match import generate_rationale_for_match
from worldcup.rationale.prompts import MatchPromptContext, build_match_rationale_prompt
from scripts.seed_competition import seed


def test_build_prompt_includes_all_context_sections():
    ctx = MatchPromptContext(
        home_name="Brazil", away_name="France",
        stage="group", group_label="G",
        kickoff_iso="2026-06-15T20:00 UTC",
        home_rating=1790.0, away_rating=1830.0,
        our_p_home=0.40, our_p_draw=0.28, our_p_away=0.32,
        poly_p_home=0.45, poly_p_draw=0.27, poly_p_away=0.28,
        edge_vs_poly=-0.05,
        home_recent_news=["Vinicius doubtful", "Tite presser"],
        away_recent_news=["Mbappe quotes from camp"],
        home_sentiment=-0.1, away_sentiment=0.3,
    )
    prompt = build_match_rationale_prompt(ctx)
    assert "Brazil vs France" in prompt
    assert "Group G" in prompt
    assert "1790" in prompt
    assert "1830" in prompt
    assert "Polymarket" in prompt
    assert "-5pp" in prompt or "−5pp" in prompt or "+5pp" not in prompt
    assert "Vinicius doubtful" in prompt
    assert "Mbappe quotes from camp" in prompt
    assert "REQUIREMENTS" in prompt


def test_build_prompt_omits_polymarket_when_unavailable():
    ctx = MatchPromptContext(
        home_name="Brazil", away_name="France",
        stage="group", group_label=None,
        kickoff_iso="2026-06-15T20:00 UTC",
        home_rating=1790.0, away_rating=1830.0,
        our_p_home=0.4, our_p_draw=0.3, our_p_away=0.3,
        poly_p_home=None, poly_p_draw=None, poly_p_away=None,
        edge_vs_poly=0.0,
        home_recent_news=[], away_recent_news=[],
        home_sentiment=None, away_sentiment=None,
    )
    prompt = build_match_rationale_prompt(ctx)
    assert "Polymarket: no per-match market available" in prompt
    assert "Edge vs market" not in prompt


async def _seed_full_context(snapshot_id_holder: dict):
    """Seed competition, 2 teams + ratings + 1 match + 1 forecast + a few news/sentiment rows."""
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
        now = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        session.add_all([
            TeamRating(team_id=teams["Brazil"].id, rating=1790.0, last_updated=now, source="seed"),
            TeamRating(team_id=teams["France"].id, rating=1830.0, last_updated=now, source="seed"),
        ])
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
            snapshot_date=now,
            snapshot_trigger="manual",
            poly_odds_hash="x",
            model_state_hash="y",
            model_version="simulator-v0",
        )
        session.add(snap)
        await session.flush()
        forecast = MatchForecast(
            snapshot_id=snap.id,
            match_id=match.id,
            p_home=0.40, p_draw=0.28, p_away=0.32,
            p_home_poly=None, p_draw_poly=None, p_away_poly=None,
            edge_vs_poly=0.0,
        )
        session.add(forecast)
        session.add(NewsItem(
            competition_id=comp.id, team_id=teams["Brazil"].id,
            source="gnews", url="https://news/1", ts=now,
            title="Vinicius doubtful for Brazil",
        ))
        session.add(SentimentScore(
            target_type="team", target_id=teams["Brazil"].id,
            ts=now, score=-0.2, confidence=0.8, model_version="team-rollup-v0",
        ))
        await session.commit()
        await session.refresh(forecast)
        snapshot_id_holder["snap_id"] = snap.id
        snapshot_id_holder["forecast_id"] = forecast.id


@pytest.mark.asyncio
async def test_generate_rationale_for_match_persists_text():
    holder = {}
    await _seed_full_context(holder)

    client = FakeClaudeClient(canned_completion="Brazil are slightly weaker on paper but home form should keep them competitive against France.")
    result = await generate_rationale_for_match(
        client,
        match_forecast_id=holder["forecast_id"],
    )

    assert result is not None
    assert result["rationale_written"] is True
    assert client.calls == 1

    async with get_session() as session:
        mf = (await session.execute(
            select(MatchForecast).where(MatchForecast.id == holder["forecast_id"])
        )).scalar_one()
    assert mf.rationale_md is not None
    assert "Brazil" in mf.rationale_md


@pytest.mark.asyncio
async def test_generate_rationale_skips_when_client_disabled():
    holder = {}
    await _seed_full_context(holder)

    client = FakeClaudeClient(canned_completion="ignored", disabled=True)
    result = await generate_rationale_for_match(
        client,
        match_forecast_id=holder["forecast_id"],
    )

    assert result["rationale_written"] is False

    async with get_session() as session:
        mf = (await session.execute(
            select(MatchForecast).where(MatchForecast.id == holder["forecast_id"])
        )).scalar_one()
    assert mf.rationale_md is None
