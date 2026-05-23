"""Drive the Monte Carlo simulator + persist tournament-level forecasts.

This module replaces `model/naive.py`'s role for tournament outlook. It:
  1. Loads all teams + their Elo ratings + competition row
  2. Builds the 12 groups from team country_code prefix
     (A1..A4 → group A, etc.)
  3. Runs simulate_tournament(...) for N iterations
  4. Persists a ForecastSnapshot + TournamentForecast rows
  5. Computes edge_vs_poly using the latest Polymarket outright snapshot
"""

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.model.elo import INITIAL_RATING
from worldcap.model.simulator.orchestrator import simulate_tournament
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    OddsSnapshot,
    Team,
    TeamRating,
    TournamentForecast,
)


MODEL_VERSION = "simulator-v0-elo"


def _hash_payload(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _group_teams_by_country_code(teams: list[Team]) -> list[list[Team]]:
    """Group teams by the *letter prefix* of their country_code (A1..A4 → group A).

    Teams without a recognisable prefix are dropped. Each group is sorted by
    code suffix for stable ordering.
    """
    by_group: dict[str, list[Team]] = defaultdict(list)
    for t in teams:
        code = (t.country_code or "").strip()
        if not code or not code[0].isalpha():
            continue
        prefix = code[0].upper()
        by_group[prefix].append(t)
    # Sort each group by full code so order is deterministic across runs
    for label in by_group:
        by_group[label].sort(key=lambda t: (t.country_code or ""))
    # Only include groups with exactly 4 teams
    out = []
    for label in sorted(by_group):
        if len(by_group[label]) == 4:
            out.append(by_group[label])
    return out


async def generate_simulated_forecast(
    trigger: str = "manual",
    n_iterations: int = 10_000,
    seed: int | None = None,
) -> ForecastSnapshot:
    """Run the Monte Carlo simulator and persist tournament-level forecasts."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one()

        teams = (await session.execute(select(Team))).scalars().all()
        ratings_rows = (await session.execute(select(TeamRating))).scalars().all()
        ratings_by_team_id = {r.team_id: r.rating for r in ratings_rows}

        # Build groups
        groups = _group_teams_by_country_code(teams)
        if len(groups) != 12:
            # Skip simulator if the competition isn't fully seeded; still write
            # an (empty) snapshot so downstream `generate_match_forecasts` has
            # something to attach to.
            snap = ForecastSnapshot(
                competition_id=comp.id,
                snapshot_date=now,
                snapshot_trigger=trigger,
                poly_odds_hash="",
                model_state_hash=_hash_payload(sorted(ratings_by_team_id.items())),
                model_version=MODEL_VERSION,
            )
            session.add(snap)
            await session.commit()
            await session.refresh(snap)
            return snap

        ratings_for_sim = {t: ratings_by_team_id.get(t.id, INITIAL_RATING) for t in teams}

        # Polymarket outright snapshot
        poly = (await session.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.competition_id == comp.id)
            .where(OddsSnapshot.market_type == "outright_winner")
            .order_by(OddsSnapshot.ts.desc())
        )).scalars().first()
        poly_by_name: dict[str, float] = dict(poly.outcomes) if poly else {}

    # Run simulator outside the session (CPU-only, no DB)
    sim_result = simulate_tournament(
        groups,
        ratings_for_sim,
        n_iterations=n_iterations,
        seed=seed,
    )

    # Persist snapshot + forecasts
    async with get_session() as session:
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=now,
            snapshot_trigger=trigger,
            poly_odds_hash=_hash_payload(sorted(poly_by_name.items())),
            model_state_hash=_hash_payload(sorted((t.id, r) for t, r in ratings_for_sim.items())),
            model_version=MODEL_VERSION,
        )
        session.add(snap)
        await session.flush()

        for t in teams:
            p_champion = sim_result.p_champion(t)
            p_runner_up = sim_result.p_runner_up(t)
            p_semi = sim_result.p_semi(t)
            p_top_group = sim_result.p_top_group(t)
            poly_p = poly_by_name.get(t.name)
            edge = (p_champion - poly_p) if poly_p is not None else 0.0
            session.add(TournamentForecast(
                snapshot_id=snap.id,
                team_id=t.id,
                p_champion=p_champion,
                p_runner_up=p_runner_up,
                p_semi=p_semi,
                p_top_group=p_top_group,
                poly_p_champion=poly_p,
                edge_vs_poly=edge,
            ))
        await session.commit()
        await session.refresh(snap)
    return snap
