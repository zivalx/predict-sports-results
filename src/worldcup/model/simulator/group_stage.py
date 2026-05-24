"""Simulate a 4-team group: play all 6 matches and return finishing order.

Pure function. Threads `rng` through every random choice so simulations are
deterministic given a seed.

Match probabilities come from the existing `match_probabilities` (Elo-based).
Strength is approximated from rating by a simple mapping: rating - 1500 mapped
linearly to a per-team expected-goals rate centered at 1.4 — typical WC value.
"""

import random
from itertools import combinations
from typing import Any

from worldcup.model.match import match_probabilities
from worldcup.model.simulator.score_sampling import sample_outcome, sample_score
from worldcup.model.simulator.tiebreakers import GroupMatch, resolve_standings


GROUP_SIZE = 4


def _rating_to_strength(rating: float) -> float:
    """Convert Elo rating to expected-goals rate. Centered at 1500 → 1.4 goals/match."""
    return max(0.3, 1.4 + (rating - 1500.0) / 250.0)


def simulate_group(
    teams: list[Any],
    ratings_by_team: dict[Any, float],
    *,
    rng: random.Random,
) -> tuple[list[Any], dict]:
    """Play all 6 round-robin matches and return (standings, stats_map).

    Returns:
        ordered_teams: the 4 teams in finishing order (winner first).
        standings_map: dict mapping each team → its _Standing (points, gd, gf).

    For each pair (home, away), `match_probabilities` produces (p_home, p_draw, p_away)
    using the home team's Elo + the standard 100-pt home advantage. We then sample
    an outcome and a scoreline.

    `teams`: exactly 4 opaque team handles.
    `ratings_by_team`: rating per team; missing entries default to 1500.0.
    """
    if len(teams) != GROUP_SIZE:
        raise ValueError(f"simulate_group requires exactly {GROUP_SIZE} teams; got {len(teams)}")

    matches: list[GroupMatch] = []
    for home, away in combinations(teams, 2):
        home_r = ratings_by_team.get(home, 1500.0)
        away_r = ratings_by_team.get(away, 1500.0)
        probs = match_probabilities(home_r, away_r)
        outcome = sample_outcome(probs["home"], probs["draw"], probs["away"], rng=rng)
        h_goals, a_goals = sample_score(
            outcome,
            home_strength=_rating_to_strength(home_r),
            away_strength=_rating_to_strength(away_r),
            rng=rng,
        )
        matches.append(GroupMatch(home=home, away=away, home_goals=h_goals, away_goals=a_goals))

    ordered_teams, standings_map = resolve_standings(matches, rng=rng)
    return ordered_teams, standings_map
