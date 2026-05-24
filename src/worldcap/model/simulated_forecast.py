"""Drive the Monte Carlo simulator + persist tournament-level forecasts.

This module replaces `model/naive.py`'s role for tournament outlook. It:
  1. Loads all teams + their Elo ratings + competition row
  2. Builds the 12 groups from Match.group_label
  3. Runs simulate_tournament(...) for N iterations
  4. Persists a ForecastSnapshot + TournamentForecast rows
  5. Computes edge_vs_poly using the latest Polymarket outright snapshot
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.model.elo import INITIAL_RATING
from worldcap.model.simulator.orchestrator import SimulationResult, simulate_tournament
from worldcap.model.simulator.top_scorer import PlayerEntry
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    OddsSnapshot,
    Player,
    Team,
    TeamRating,
    TournamentForecast,
)


MODEL_VERSION = "simulator-v0-elo"


def _hash_payload(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


async def _group_teams_from_matches(session) -> list[list[Team]]:
    """Group teams by their Match.group_label (production-real grouping).

    For each unique group_label, collect the set of teams that appear in any
    match in that group. Returns 12 groups of 4 teams each, sorted by label.
    Groups that don't have exactly 4 distinct teams are dropped.
    """
    from worldcap.models import Match

    matches = (await session.execute(
        select(Match).where(Match.group_label.is_not(None))
    )).scalars().all()
    teams_by_id = {
        t.id: t for t in (await session.execute(select(Team))).scalars().all()
    }

    groups_by_label: dict[str, list] = {}
    for m in matches:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        home = teams_by_id.get(m.home_team_id)
        away = teams_by_id.get(m.away_team_id)
        if home is None or away is None:
            continue
        bucket = groups_by_label.setdefault(m.group_label, [])
        if home not in bucket:
            bucket.append(home)
        if away not in bucket:
            bucket.append(away)

    out = []
    for label in sorted(groups_by_label):
        teams = groups_by_label[label]
        if len(teams) == 4:
            out.append(teams)
    return out


async def generate_simulated_forecast(
    trigger: str = "manual",
    n_iterations: int = 10_000,
    seed: int | None = None,
) -> tuple[ForecastSnapshot, SimulationResult | None]:
    """Run the Monte Carlo simulator and persist tournament-level forecasts.

    Returns (snapshot, sim_result) where sim_result is None if the competition
    isn't fully seeded.
    """
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
        groups = await _group_teams_from_matches(session)
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
            return snap, None

        ratings_for_sim = {t: ratings_by_team_id.get(t.id, INITIAL_RATING) for t in teams}

        # Load watchlist players and build PlayerEntry list
        players_rows = (await session.execute(
            select(Player).where(Player.is_watchlist == True)
        )).scalars().all()
        team_by_id = {t.id: t for t in teams}
        player_entries: list[PlayerEntry] = []
        for p in players_rows:
            team = team_by_id.get(p.team_id)
            if team is None:
                continue
            player_entries.append(PlayerEntry(
                player_handle=p.id,  # use DB id as the hashable handle
                team=team,
                goals_per_90=p.goals_per_90,
            ))

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
        players=player_entries,
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
    return snap, sim_result
