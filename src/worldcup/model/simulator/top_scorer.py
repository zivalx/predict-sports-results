"""Sample tournament-total goals per watchlist player, identify Golden Boot winner.

Pure functions; all randomness via explicit `rng`. The orchestrator calls
`sample_iteration_top_scorer` once per simulated tournament, then aggregates
across iterations.
"""

import math
import random
from dataclasses import dataclass
from typing import Any


DEFAULT_START_PROBABILITY = 0.8


@dataclass
class PlayerEntry:
    """Lightweight player handle for the simulator.

    `team`: an opaque team handle (same identity used by other simulator pieces)
    `goals_per_90`: float, expected goals per 90 minutes played
    `start_prob`: probability the player starts a given match (defaults 0.8;
      callers can override per player)
    """
    player_handle: Any
    team: Any
    goals_per_90: float
    start_prob: float = DEFAULT_START_PROBABILITY


_MATCHES_PER_ROUND = {
    "group": 3,
    "R32": 4,
    "R16": 5,
    "QF": 6,
    "SF": 7,
    "F": 8,
    "champion": 8,
}


def _poisson_sample(rate: float, rng: random.Random) -> int:
    """Knuth's algorithm, same as in score_sampling.py. Adequate for rates < 30."""
    if rate <= 0:
        return 0
    L = math.exp(-rate)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def sample_iteration_top_scorer(
    players: list[PlayerEntry],
    team_round_this_iter: dict[Any, str],
    rng: random.Random,
) -> tuple[Any, dict[Any, int]]:
    """One iteration of top-scorer sampling.

    `team_round_this_iter` maps team handles to their max round reached this
    iteration ("group" | "R32" | "R16" | "QF" | "SF" | "F" | "champion").

    Returns:
        (winner_player_handle, goals_by_player)
        winner is None if there are no players.
    """
    if not players:
        return None, {}

    goals_by_player: dict[Any, int] = {}
    for p in players:
        round_label = team_round_this_iter.get(p.team, "group")
        matches = _MATCHES_PER_ROUND.get(round_label, 3)
        rate = p.goals_per_90 * matches * p.start_prob
        goals_by_player[p.player_handle] = _poisson_sample(rate, rng)

    # Argmax. Ties broken by random shuffling so each tied player has equal chance.
    max_goals = max(goals_by_player.values())
    tied = [p for p, g in goals_by_player.items() if g == max_goals]
    winner = rng.choice(tied)
    return winner, goals_by_player
