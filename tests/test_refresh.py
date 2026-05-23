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


GROUP_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


def _build_full_wc_fixtures():
    """48-team WC schedule from football-data-org-shaped DTOs.

    Country codes follow the {label}{i} pattern so simulated_forecast can detect
    the 12 groups via country_code prefix.
    """
    from datetime import datetime, timezone
    from worldcap.ingest.sports_data import TeamDTO, FixtureDTO

    teams = []
    for gi, label in enumerate(GROUP_LABELS):
        for ti in range(4):
            teams.append(TeamDTO(
                external_id=gi * 4 + ti + 1000,
                name=f"Team-{label}{ti+1}",
                country_code=f"{label}{ti+1}",
            ))
    # One fixture per group (we don't need all 72) — enough that the fixtures ingest runs
    fixtures = []
    for gi, label in enumerate(GROUP_LABELS):
        fixtures.append(FixtureDTO(
            external_id=10_000 + gi,
            stage="group",
            group_label=label,
            kickoff_utc=datetime(2026, 6, 11 + gi % 10, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
            home_external_id=gi * 4 + 1000,
            away_external_id=gi * 4 + 1001,
            home_score=None,
            away_score=None,
        ))
    return teams, fixtures


@pytest.fixture
def fake_full_wc_football_client():
    from unittest.mock import AsyncMock
    teams, fixtures = _build_full_wc_fixtures()
    client = AsyncMock()
    client.get_teams.return_value = teams
    client.get_fixtures.return_value = fixtures
    return client


@pytest.mark.asyncio
async def test_run_refresh_full_wc_seeds_tournament_forecasts(fake_full_wc_football_client, fake_poly_collector):
    await init_db()
    await seed()

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)
    snap = await run_refresh(
        trigger="manual",
        football_client=fake_full_wc_football_client,
        poly_collector=fake_poly_collector,
        as_of=as_of,
    )

    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        tournament_forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(teams) == 48
    assert len(tournament_forecasts) == 48
    total = sum(f.p_champion for f in tournament_forecasts)
    assert total == pytest.approx(1.0, abs=0.005)  # tiny floating-point tolerance
    # At least one team has positive p_semi
    assert any(f.p_semi > 0.0 for f in tournament_forecasts)


@pytest.fixture
def fake_gnews_collector():
    from unittest.mock import AsyncMock, MagicMock

    collector = MagicMock()
    async def fetch(spec):
        q = spec.query
        a = MagicMock()
        a.url = f"https://news.example/{q.replace(' ', '-')}-1"
        a.title = f"{q} headline"
        a.description = f"Story about {q}"
        a.published_at = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        return MagicMock(status="success", articles=[a])
    collector.fetch = AsyncMock(side_effect=fetch)
    return collector


@pytest.fixture
def fake_reddit_collector():
    from unittest.mock import AsyncMock, MagicMock

    collector = MagicMock()
    async def fetch(spec):
        post = MagicMock()
        post.id = "abc"
        post.title = "Team A1 looks strong"
        post.body = "great form"
        post.text = "Team A1 looks strong great form"
        post.author = "user"
        post.score = 100
        post.url = "https://reddit.com/r/soccer/comments/abc/"
        post.created_at = datetime(2026, 5, 23, 11, 0, tzinfo=timezone.utc)
        return MagicMock(status="success", posts=[post])
    collector.fetch = AsyncMock(side_effect=fetch)
    return collector


@pytest.mark.asyncio
async def test_run_refresh_full_wc_writes_rationales(
    fake_full_wc_football_client,
    fake_poly_collector,
    fake_gnews_collector,
    fake_reddit_collector,
):
    from worldcap.enrich.claude_client import FakeClaudeClient
    from worldcap.models import MatchForecast

    await init_db()
    await seed()

    claude = FakeClaudeClient(
        canned_completion="Strong analytical paragraph about the upcoming fixture.",
        canned_score=0.2,
        token_budget=1_000_000,
    )

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)
    snap = await run_refresh(
        trigger="manual",
        football_client=fake_full_wc_football_client,
        poly_collector=fake_poly_collector,
        gnews_collector=fake_gnews_collector,
        reddit_collector=fake_reddit_collector,
        claude_client=claude,
        as_of=as_of,
    )

    async with get_session() as session:
        forecasts = (await session.execute(
            select(MatchForecast).where(MatchForecast.snapshot_id == snap.id)
        )).scalars().all()
    # At least one rationale should be written.
    rationales = [f for f in forecasts if f.rationale_md]
    assert len(rationales) >= 1
    assert "analytical paragraph" in rationales[0].rationale_md
