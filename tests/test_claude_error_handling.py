"""Tests for Claude API error hardening (Fix 2).

Verifies that:
- score_unscored_items: per-item failures log + skip (don't crash)
- generate_rationale_for_match: failures log + return {rationale_written: False}
- run_refresh: Claude failures in sentiment/rationale don't abort the pipeline
"""

from datetime import datetime, timedelta, timezone
from itertools import combinations
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.enrich.claude_client import FakeClaudeClient
from worldcup.enrich.sentiment import score_unscored_items
from worldcup.models import (
    ForecastSnapshot,
    MatchForecast,
    NewsItem,
    SentimentScore,
    SocialPost,
    Team,
    TeamRating,
)
from worldcup.models.tournament import Competition, Match
from worldcup.rationale.match import generate_rationale_for_match
from scripts.seed_competition import seed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_content(n_posts: int = 2, n_news: int = 2):
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(Team(external_id=888, name="TestTeam", country_code="TST"))
        await session.flush()
        team = (await session.execute(select(Team))).scalar_one()
        for i in range(n_posts):
            session.add(SocialPost(
                competition_id=comp.id,
                team_id=team.id,
                platform="reddit",
                external_id=f"err{i}",
                ts=datetime(2026, 5, 23, 10, i, tzinfo=timezone.utc),
                text=f"Error test post {i}",
                url=f"https://reddit.com/err{i}",
            ))
        for j in range(n_news):
            session.add(NewsItem(
                competition_id=comp.id,
                team_id=team.id,
                source="gnews",
                url=f"https://news.example/err{j}",
                ts=datetime(2026, 5, 23, 12, j, tzinfo=timezone.utc),
                title=f"Error news {j}",
                summary=f"Error summary {j}",
            ))
        await session.commit()


async def _seed_match_context(holder: dict):
    """Seed minimal context for a MatchForecast rationale test."""
    await init_db()
    await seed()
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=901, name="ErrorHome", country_code="EHO"),
            Team(external_id=902, name="ErrorAway", country_code="EAW"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        now = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        session.add_all([
            TeamRating(team_id=teams["ErrorHome"].id, rating=1500.0, last_updated=now, source="seed"),
            TeamRating(team_id=teams["ErrorAway"].id, rating=1500.0, last_updated=now, source="seed"),
        ])
        match = Match(
            external_id=9001,
            competition_id=comp.id,
            stage="group",
            group_label="Z",
            home_team_id=teams["ErrorHome"].id,
            away_team_id=teams["ErrorAway"].id,
            kickoff_utc=datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        )
        session.add(match)
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=now,
            snapshot_trigger="manual",
            poly_odds_hash="err-x",
            model_state_hash="err-y",
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
        await session.commit()
        await session.refresh(forecast)
        holder["forecast_id"] = forecast.id


# ---------------------------------------------------------------------------
# Tests: score_unscored_items with erroring client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_unscored_items_call_error_skips_item_and_continues():
    """A network error on every item should return zeros without crashing."""
    await init_db()
    await seed()
    await _seed_content(n_posts=3, n_news=2)

    import httpx
    error_client = FakeClaudeClient(raise_on_call=httpx.HTTPError("connection refused"))

    summary = await score_unscored_items(error_client, limit=100)

    # No items scored — all failed
    assert summary["posts_scored"] == 0
    assert summary["items_scored"] == 0
    # No SentimentScore rows written
    async with get_session() as session:
        scores = (await session.execute(select(SentimentScore))).scalars().all()
    assert len(scores) == 0


@pytest.mark.asyncio
async def test_score_unscored_items_partial_failure_continues():
    """When only first call raises, remaining items are still scored."""
    await init_db()
    await seed()
    await _seed_content(n_posts=3, n_news=0)

    import httpx

    call_count = 0
    original_init = FakeClaudeClient.__init__

    class FirstFailsClient(FakeClaudeClient):
        async def score_text(self, text, *, model):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPError("transient failure")
            return await super().score_text(text, model=model)

    client = FirstFailsClient(canned_score=0.5, token_budget=100_000)
    summary = await score_unscored_items(client, limit=100)

    # First item skipped, items 2 and 3 scored
    assert summary["posts_scored"] == 2
    assert summary["items_scored"] == 0


@pytest.mark.asyncio
async def test_score_unscored_items_generic_exception_does_not_crash():
    """Any arbitrary exception type should be caught and logged."""
    await init_db()
    await seed()
    await _seed_content(n_posts=1, n_news=1)

    error_client = FakeClaudeClient(raise_on_call=RuntimeError("unexpected failure"))
    summary = await score_unscored_items(error_client, limit=100)
    # Graceful: returns counts of zero
    assert summary["posts_scored"] + summary["items_scored"] == 0


# ---------------------------------------------------------------------------
# Tests: generate_rationale_for_match with erroring client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_rationale_error_returns_rationale_written_false():
    holder = {}
    await _seed_match_context(holder)

    import httpx
    error_client = FakeClaudeClient(raise_on_call=httpx.HTTPError("rate limit"))
    result = await generate_rationale_for_match(error_client, match_forecast_id=holder["forecast_id"])

    assert result["rationale_written"] is False
    assert "error" in result  # error field is populated


@pytest.mark.asyncio
async def test_generate_rationale_error_leaves_rationale_md_none():
    holder = {}
    await _seed_match_context(holder)

    import httpx
    error_client = FakeClaudeClient(raise_on_call=httpx.HTTPError("timeout"))
    await generate_rationale_for_match(error_client, match_forecast_id=holder["forecast_id"])

    async with get_session() as session:
        mf = (await session.execute(
            select(MatchForecast).where(MatchForecast.id == holder["forecast_id"])
        )).scalar_one()
    assert mf.rationale_md is None


# ---------------------------------------------------------------------------
# Tests: run_refresh survives all-erroring Claude client
# ---------------------------------------------------------------------------

GROUP_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


def _build_full_wc_fixtures():
    from worldcup.ingest.sports_data import FixtureDTO, TeamDTO

    teams = []
    for gi, label in enumerate(GROUP_LABELS):
        for ti in range(4):
            teams.append(TeamDTO(
                external_id=gi * 4 + ti + 2000,
                name=f"ErrTeam-{label}{ti + 1}",
                country_code=f"{label}{ti + 1}",
            ))

    fixtures = []
    match_ext_id = 20000
    for gi, label in enumerate(GROUP_LABELS):
        group_members_ext = [gi * 4 + ti + 2000 for ti in range(4)]
        for home_ext, away_ext in combinations(group_members_ext, 2):
            fixtures.append(FixtureDTO(
                external_id=match_ext_id,
                stage="group",
                group_label=label,
                kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc) + timedelta(hours=match_ext_id - 20000),
                status="SCHEDULED",
                home_external_id=home_ext,
                away_external_id=away_ext,
                home_score=None,
                away_score=None,
            ))
            match_ext_id += 1
    return teams, fixtures


@pytest.mark.asyncio
async def test_run_refresh_survives_erroring_claude_client(
):
    """Even when all Claude calls fail, the pipeline completes and returns a ForecastSnapshot."""
    from worldcup.jobs.refresh import run_refresh
    from worldcup.models import ForecastSnapshot
    import httpx

    await init_db()
    await seed()

    teams, fixtures = _build_full_wc_fixtures()

    football_client = AsyncMock()
    football_client.get_teams.return_value = teams
    football_client.get_fixtures.return_value = fixtures

    market = MagicMock()
    market.question = "Winner of FIFA World Cup 2026"
    market.outcomes = ["ErrTeam-A1"]
    market.outcome_prices = [0.10]
    market.volume = 50000.0
    poly_result = MagicMock()
    poly_result.status = "success"
    poly_result.markets = [market]
    poly_collector = MagicMock()
    poly_collector.fetch_markets = AsyncMock(return_value=poly_result)

    # Client that raises on every call
    error_claude = FakeClaudeClient(raise_on_call=httpx.HTTPError("API unavailable"))

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)
    snap = await run_refresh(
        trigger="manual",
        football_client=football_client,
        poly_collector=poly_collector,
        claude_client=error_claude,
        as_of=as_of,
    )

    # Pipeline must complete and return a snapshot
    assert isinstance(snap, ForecastSnapshot)

    # Sentiment should be zero (all failed)
    async with get_session() as session:
        scores = (await session.execute(select(SentimentScore))).scalars().all()
    assert len(scores) == 0

    # Rationales should all be None (all failed)
    async with get_session() as session:
        forecasts = (await session.execute(
            select(MatchForecast).where(MatchForecast.snapshot_id == snap.id)
        )).scalars().all()
    # Pipeline didn't crash — forecasts may or may not exist depending on fixture horizon
    rationales = [f for f in forecasts if f.rationale_md is not None]
    assert len(rationales) == 0
