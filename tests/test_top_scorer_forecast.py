from datetime import datetime, timedelta, timezone
from itertools import combinations

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.model.simulated_forecast import generate_simulated_forecast
from worldcup.model.top_scorer_forecast import generate_top_scorer_forecast
from worldcup.models import (
    OddsSnapshot,
    Player,
    Team,
    TeamRating,
    TopScorerForecast,
)
from worldcup.models.tournament import Competition, Match
from scripts.seed_competition import seed


GROUP_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


async def _seed_wc_teams_ratings_and_players(as_of: datetime):
    """Seed 48 teams + ratings + players + 72 group-stage matches."""
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()

        # Seed 48 teams
        for gi, label in enumerate(GROUP_LABELS):
            for ti in range(4):
                session.add(Team(
                    external_id=gi * 4 + ti + 1000,
                    name=f"Team-{label}{ti+1}",
                    country_code=f"{label}{ti+1}",
                ))
        await session.flush()
        teams = (await session.execute(select(Team))).scalars().all()
        teams_by_code = {t.country_code: t for t in teams}

        # Seed team ratings
        for t in teams:
            session.add(TeamRating(
                team_id=t.id, rating=1500.0,
                last_updated=as_of, source="seed",
            ))

        # Add 3 watchlist players on team A1
        team_a1 = next(t for t in teams if t.country_code == "A1")
        session.add_all([
            Player(name="Striker A", team_id=team_a1.id, goals_per_90=0.9, is_watchlist=True),
            Player(name="Striker B", team_id=team_a1.id, goals_per_90=0.5, is_watchlist=True),
            Player(name="Striker C", team_id=team_a1.id, goals_per_90=0.3, is_watchlist=True),
        ])

        # Group-stage matches: 6 per group (round-robin among 4 teams)
        match_ext_id = 20000
        for gi, label in enumerate(GROUP_LABELS):
            members = [teams_by_code[f"{label}{i+1}"] for i in range(4)]
            for home, away in combinations(members, 2):
                session.add(Match(
                    external_id=match_ext_id,
                    competition_id=comp.id,
                    stage="group",
                    group_label=label,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc) + timedelta(hours=match_ext_id - 20000),
                    status="SCHEDULED",
                ))
                match_ext_id += 1

        await session.commit()


@pytest.mark.asyncio
async def test_generate_writes_one_row_per_watchlist_player():
    await init_db()
    await seed()
    as_of = datetime(2026, 5, 23, tzinfo=timezone.utc)
    await _seed_wc_teams_ratings_and_players(as_of)

    snap, sim_result = await generate_simulated_forecast(
        trigger="manual", n_iterations=200, seed=42,
    )
    assert sim_result is not None

    summary = await generate_top_scorer_forecast(snap.id, sim_result)
    assert summary["rows_written"] == 3
    assert summary["with_poly"] == 0  # no top-scorer market seeded

    async with get_session() as session:
        rows = (await session.execute(
            select(TopScorerForecast).where(TopScorerForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(rows) == 3
    by_name_via_player_id: dict[int, TopScorerForecast] = {r.player_id: r for r in rows}
    async with get_session() as session:
        players = (await session.execute(select(Player))).scalars().all()
    name_by_id = {p.id: p.name for p in players}
    by_name = {name_by_id[pid]: row for pid, row in by_name_via_player_id.items()}
    # Best player should have the highest p_golden_boot
    assert by_name["Striker A"].p_golden_boot >= by_name["Striker B"].p_golden_boot
    assert by_name["Striker B"].p_golden_boot >= by_name["Striker C"].p_golden_boot
    # All forecasts have non-negative expected_goals
    for r in rows:
        assert r.expected_goals >= 0


@pytest.mark.asyncio
async def test_generate_uses_polymarket_when_available():
    await init_db()
    await seed()
    as_of = datetime(2026, 5, 23, tzinfo=timezone.utc)
    await _seed_wc_teams_ratings_and_players(as_of)

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="top_scorer",
            source="polymarket",
            ts=as_of,
            outcomes={"Striker A": 0.20, "Striker B": 0.05},  # Striker C absent
        ))
        await session.commit()

    snap, sim_result = await generate_simulated_forecast(
        trigger="manual", n_iterations=200, seed=42,
    )
    summary = await generate_top_scorer_forecast(snap.id, sim_result)
    assert summary["with_poly"] == 2

    async with get_session() as session:
        rows = (await session.execute(
            select(TopScorerForecast).where(TopScorerForecast.snapshot_id == snap.id)
        )).scalars().all()
        players = {p.id: p for p in (await session.execute(select(Player))).scalars().all()}

    by_name = {players[r.player_id].name: r for r in rows}
    assert by_name["Striker A"].poly_p_top_scorer == 0.20
    assert by_name["Striker B"].poly_p_top_scorer == 0.05
    assert by_name["Striker C"].poly_p_top_scorer is None
    # edge = our_p - poly_p
    assert by_name["Striker A"].edge_vs_poly == pytest.approx(by_name["Striker A"].p_golden_boot - 0.20, abs=1e-9)
    assert by_name["Striker C"].edge_vs_poly == 0.0
