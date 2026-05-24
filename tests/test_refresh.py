from datetime import datetime, timedelta, timezone
from itertools import combinations
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

    # Fixture kickoff is 2026-06-11; as_of is 2026-06-05 (6 days before).
    # generate_match_forecasts now covers all future scheduled matches.
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
    assert len(match_forecasts) == 1       # Brazil vs France (only scheduled fixture)

    mf = match_forecasts[0]
    assert mf.p_home + mf.p_draw + mf.p_away == pytest.approx(1.0, abs=1e-9)
    assert mf.model_version == "elo-v0"

    out_dir = get_settings().digest_output_dir
    assert (out_dir / "2026-06-05.md").exists()
    assert get_settings().whatsapp_pickup_path.exists()


GROUP_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


def _build_full_wc_fixtures():
    """48-team WC schedule with all 72 group-stage fixtures from football-data-org-shaped DTOs.

    Country codes follow the {label}{i} pattern. Generates all 6 matches per group
    (round-robin among 4 teams).
    """
    from worldcap.ingest.sports_data import TeamDTO, FixtureDTO

    teams = []
    for gi, label in enumerate(GROUP_LABELS):
        for ti in range(4):
            teams.append(TeamDTO(
                external_id=gi * 4 + ti + 1000,
                name=f"Team-{label}{ti+1}",
                country_code=f"{label}{ti+1}",
            ))

    # All 72 group-stage fixtures: 6 per group (round-robin among 4 teams)
    fixtures = []
    match_ext_id = 10000
    for gi, label in enumerate(GROUP_LABELS):
        # Get the 4 team external IDs for this group
        group_members_ext = [gi * 4 + ti + 1000 for ti in range(4)]
        # Generate all combinations (6 total)
        for home_ext, away_ext in combinations(group_members_ext, 2):
            fixtures.append(FixtureDTO(
                external_id=match_ext_id,
                stage="group",
                group_label=label,
                kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc) + timedelta(hours=match_ext_id - 10000),
                status="SCHEDULED",
                home_external_id=home_ext,
                away_external_id=away_ext,
                home_score=None,
                away_score=None,
            ))
            match_ext_id += 1

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


@pytest.mark.asyncio
async def test_rationale_loop_only_processes_matches_within_horizon(
    fake_poly_collector,
):
    """Two matches: one 5 days out, one 30 days out.
    After run_refresh with rationale_horizon_days=14, only the near match gets
    rationale_md set; the far match doesn't.
    """
    from unittest.mock import AsyncMock
    from worldcap.enrich.claude_client import FakeClaudeClient
    from worldcap.ingest.sports_data import FixtureDTO, TeamDTO

    await init_db()
    await seed()

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)
    near_kickoff = as_of + timedelta(days=5)   # within 14-day rationale horizon
    far_kickoff = as_of + timedelta(days=30)   # outside 14-day rationale horizon

    client = AsyncMock()
    client.get_teams.return_value = [
        TeamDTO(external_id=801, name="Spain", country_code="ESP"),
        TeamDTO(external_id=802, name="Portugal", country_code="POR"),
        TeamDTO(external_id=803, name="Netherlands", country_code="NED"),
        TeamDTO(external_id=804, name="Belgium", country_code="BEL"),
    ]
    client.get_fixtures.return_value = [
        FixtureDTO(
            external_id=901,
            stage="group",
            group_label="C",
            kickoff_utc=near_kickoff,
            status="SCHEDULED",
            home_external_id=801,
            away_external_id=802,
            home_score=None,
            away_score=None,
        ),
        FixtureDTO(
            external_id=902,
            stage="group",
            group_label="D",
            kickoff_utc=far_kickoff,
            status="SCHEDULED",
            home_external_id=803,
            away_external_id=804,
            home_score=None,
            away_score=None,
        ),
    ]

    claude = FakeClaudeClient(
        canned_completion="Near-match rationale text.",
        canned_score=0.1,
        token_budget=1_000_000,
    )

    snap = await run_refresh(
        trigger="manual",
        football_client=client,
        poly_collector=fake_poly_collector,
        claude_client=claude,
        as_of=as_of,
    )

    async with get_session() as session:
        from worldcap.models import Match
        forecasts = (await session.execute(
            select(MatchForecast, Match)
            .join(Match, MatchForecast.match_id == Match.id)
            .where(MatchForecast.snapshot_id == snap.id)
            .order_by(Match.kickoff_utc.asc())
        )).all()

    assert len(forecasts) == 2, "Both matches should have probability forecasts"

    # Ordered by kickoff_utc asc: index 0 = near match (5 days), index 1 = far match (30 days).
    near_mf, near_match = forecasts[0]
    far_mf, far_match = forecasts[1]

    # Confirm ordering is correct (naive datetime comparison is fine for ordering).
    assert near_match.kickoff_utc < far_match.kickoff_utc

    # Near match (within 14-day rationale horizon) should have rationale; far match should not.
    assert near_mf.rationale_md is not None, "Near match should have rationale"
    assert far_mf.rationale_md is None, "Far match should NOT have rationale"


@pytest.mark.asyncio
async def test_run_refresh_full_wc_writes_top_scorer_forecasts(
    fake_full_wc_football_client,
    fake_poly_collector,
):
    from worldcap.models import Player, TopScorerForecast

    await init_db()
    await seed()

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)

    # First run the pipeline once to seed the 48 teams via the fixtures ingest
    # (we need them in the DB before adding Player rows that FK to them).
    snap0 = await run_refresh(
        trigger="manual",
        football_client=fake_full_wc_football_client,
        poly_collector=fake_poly_collector,
        as_of=as_of,
    )
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        assert len(teams) == 48
        # Add 3 watchlist players manually
        team_a1 = next(t for t in teams if t.country_code == "A1")
        team_b1 = next(t for t in teams if t.country_code == "B1")
        team_c1 = next(t for t in teams if t.country_code == "C1")
        session.add_all([
            Player(name="Player A1", team_id=team_a1.id, goals_per_90=0.9, is_watchlist=True),
            Player(name="Player B1", team_id=team_b1.id, goals_per_90=0.6, is_watchlist=True),
            Player(name="Player C1", team_id=team_c1.id, goals_per_90=0.4, is_watchlist=True),
        ])
        await session.commit()

    # Now re-run; this time top-scorer forecasts should be written.
    snap = await run_refresh(
        trigger="manual",
        football_client=fake_full_wc_football_client,
        poly_collector=fake_poly_collector,
        as_of=as_of,
    )

    async with get_session() as session:
        rows = (await session.execute(
            select(TopScorerForecast).where(TopScorerForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(rows) == 3
    # The best player (highest goals_per_90 on team A1) should have the highest p_golden_boot
    by_player_id = {r.player_id: r for r in rows}
    async with get_session() as session:
        players = (await session.execute(select(Player))).scalars().all()
    p_by_name = {p.name: p for p in players}
    a1_row = by_player_id[p_by_name["Player A1"].id]
    c1_row = by_player_id[p_by_name["Player C1"].id]
    assert a1_row.p_golden_boot >= c1_row.p_golden_boot
