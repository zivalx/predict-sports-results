"""Simulate a single-elimination knockout bracket starting from 32 seeded teams.

For Plan 3 v0 the seeding scheme is simple: the input list of 32 teams is
consumed pairwise in order. Winners advance in order so the bracket structure
collapses naturally over R32 → R16 → QF → SF → F.

Knockout matches use match_probabilities with home_advantage=0 (treating all
knockouts as neutral venues). On a sampled draw, a coin flip picks the advancer
— v0 simplification in lieu of an extra-time / penalties model.

Returns:
    {
        "champion": Team,
        "runner_up": Team,
        "semifinalists": list[Team],  # 4 teams who reached the SF (incl. finalists)
    }
"""

import random
from typing import Any

from worldcap.model.match import match_probabilities
from worldcap.model.simulator.score_sampling import sample_outcome


BRACKET_R32_TEAMS = 32


def _play_knockout_match(
    home: Any,
    away: Any,
    ratings: dict[Any, float],
    rng: random.Random,
) -> Any:
    """Return the team that advances (no draws in knockouts)."""
    home_r = ratings.get(home, 1500.0)
    away_r = ratings.get(away, 1500.0)
    # Knockouts have no draws — use draw_pct=0 to collapse all probability to home/away
    probs = match_probabilities(home_r, away_r, home_advantage=0.0, draw_pct=0.0)
    outcome = sample_outcome(probs["home"], probs["draw"], probs["away"], rng=rng)
    if outcome == "home":
        return home
    return away


def _play_round(
    teams: list[Any],
    ratings: dict[Any, float],
    rng: random.Random,
) -> list[Any]:
    """Play a knockout round: pairs are (teams[0], teams[1]), (teams[2], teams[3]), ..."""
    winners: list[Any] = []
    for i in range(0, len(teams), 2):
        winners.append(_play_knockout_match(teams[i], teams[i + 1], ratings, rng))
    return winners


def simulate_knockout(
    seeded_teams: list[Any],
    ratings_by_team: dict[Any, float],
    *,
    rng: random.Random,
) -> dict:
    """Simulate R32 → F starting from 32 seeded teams.

    Returns a dict with keys champion, runner_up, semifinalists.
    """
    if len(seeded_teams) != BRACKET_R32_TEAMS:
        raise ValueError(
            f"simulate_knockout requires exactly {BRACKET_R32_TEAMS} teams; got {len(seeded_teams)}"
        )

    r16 = _play_round(seeded_teams, ratings_by_team, rng)
    qf = _play_round(r16, ratings_by_team, rng)
    sf = _play_round(qf, ratings_by_team, rng)
    semifinalists = list(sf)  # capture before SF round mutates
    finalists = _play_round(sf, ratings_by_team, rng)
    champion = _play_knockout_match(finalists[0], finalists[1], ratings_by_team, rng)
    runner_up = finalists[1] if champion == finalists[0] else finalists[0]

    return {
        "champion": champion,
        "runner_up": runner_up,
        "semifinalists": semifinalists,
    }
