from datetime import datetime, timedelta, timezone
from itertools import combinations

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.model.simulated_forecast import generate_simulated_forecast
from worldcap.models import (
    ForecastSnapshot,
    OddsSnapshot,
    Team,
    TeamRating,
    TournamentForecast,
)
from worldcap.models.tournament import Competition, Match
from scripts.seed_competition import seed


GROUP_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]


async def _seed_wc_teams_and_ratings(as_of: datetime):
    """Seed 48 teams (4 per group, groups A..L) with default Elo rating and 72 group-stage matches."""
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()

        # Seed 48 teams (4 per group)
        for gi, group_label in enumerate(GROUP_LABELS):
            for ti in range(4):
                ext = gi * 4 + ti + 1000  # arbitrary external ids
                session.add(Team(
                    external_id=ext,
                    name=f"Team-{group_label}{ti+1}",
                    country_code=f"{group_label}{ti+1}",
                ))
        await session.flush()

        teams = (await session.execute(select(Team))).scalars().all()
        teams_by_code = {t.country_code: t for t in teams}

        # Seed team ratings
        for t in teams:
            session.add(TeamRating(
                team_id=t.id,
                rating=1500.0,
                last_updated=as_of,
                source="seed",
            ))

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
async def test_simulated_forecast_produces_tournament_forecast_rows():
    await init_db()
    await seed()
    as_of = datetime(2026, 5, 23, tzinfo=timezone.utc)
    await _seed_wc_teams_and_ratings(as_of)

    # Polymarket outright snapshot (so edge_vs_poly is non-trivial)
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=as_of,
            outcomes={"Team-A1": 0.10, "Team-B1": 0.05},
        ))
        await session.commit()

    snap, sim_result = await generate_simulated_forecast(trigger="manual", n_iterations=200, seed=42)
    assert isinstance(snap, ForecastSnapshot)
    assert snap.snapshot_trigger == "manual"
    assert snap.model_version.startswith("simulator-v0")
    assert sim_result is not None

    async with get_session() as session:
        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
    # One forecast row per team (48)
    assert len(forecasts) == 48
    # Champion probabilities sum to 1.0
    total = sum(f.p_champion for f in forecasts)
    assert total == pytest.approx(1.0, abs=1e-9)
    # poly_p_champion populated only for teams that appeared in the market
    by_team = {f.team_id: f for f in forecasts}
    async with get_session() as session:
        team_a1 = (await session.execute(select(Team).where(Team.country_code == "A1"))).scalar_one()
        team_b1 = (await session.execute(select(Team).where(Team.country_code == "B1"))).scalar_one()
        team_c1 = (await session.execute(select(Team).where(Team.country_code == "C1"))).scalar_one()
    assert by_team[team_a1.id].poly_p_champion == 0.10
    assert by_team[team_b1.id].poly_p_champion == 0.05
    assert by_team[team_c1.id].poly_p_champion is None
    # edge_vs_poly = our_p_champion - poly_p_champion
    assert by_team[team_a1.id].edge_vs_poly == pytest.approx(
        by_team[team_a1.id].p_champion - 0.10, abs=1e-9
    )


@pytest.mark.asyncio
async def test_simulated_forecast_handles_missing_polymarket_snapshot():
    await init_db()
    await seed()
    as_of = datetime(2026, 5, 23, tzinfo=timezone.utc)
    await _seed_wc_teams_and_ratings(as_of)
    # No OddsSnapshot inserted.

    snap, sim_result = await generate_simulated_forecast(trigger="manual", n_iterations=100, seed=42)
    assert sim_result is not None

    async with get_session() as session:
        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(forecasts) == 48
    assert all(f.poly_p_champion is None for f in forecasts)
    assert all(f.edge_vs_poly == 0.0 for f in forecasts)
