"""Sample concrete match outcomes (winner + scoreline) from match probabilities.

These are pure functions; all randomness threads through an explicit `rng`
argument so the entire simulator is deterministic given a seed.

The score model is intentionally simple — for v0 we care more about *correct*
outcomes (winner consistent with the sampled result) than statistically faithful
scorelines. Plan 5 (Golden Boot) will revisit when player-level goal attribution
matters.
"""

import random
from typing import Literal

Outcome = Literal["home", "draw", "away"]


def sample_outcome(p_home: float, p_draw: float, p_away: float, *, rng: random.Random) -> Outcome:
    """Sample one of {"home", "draw", "away"} weighted by the given probabilities.

    Probabilities are not strictly validated to sum to 1 (callers from
    `match_probabilities` guarantee this), but ordering is fixed: home, draw, away.
    """
    r = rng.random()
    if r < p_home:
        return "home"
    if r < p_home + p_draw:
        return "draw"
    return "away"


def sample_score(
    outcome: Outcome,
    home_strength: float,
    away_strength: float,
    *,
    rng: random.Random,
) -> tuple[int, int]:
    """Sample a scoreline consistent with the outcome.

    `home_strength` / `away_strength` are loose "expected goals" per team — a
    typical WC value is 1.3-1.6. The function returns (home_goals, away_goals)
    as non-negative integers; the winner (per `outcome`) has strictly more goals.

    Implementation: independent Poisson draws via stdlib (no numpy). If the
    draw doesn't match the requested outcome (rare at moderate strengths), we
    nudge one team's score by 1 to satisfy the invariant.
    """
    if outcome not in ("home", "draw", "away"):
        raise ValueError(f"outcome must be 'home', 'draw', or 'away'; got {outcome!r}")

    def _poisson(rate: float) -> int:
        """Knuth's algorithm — fine for rates < 30 (always our case)."""
        L = pow(2.71828182846, -rate)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1

    h = _poisson(max(0.1, home_strength))
    a = _poisson(max(0.1, away_strength))

    if outcome == "home" and h <= a:
        h = a + 1
    elif outcome == "away" and a <= h:
        a = h + 1
    elif outcome == "draw" and h != a:
        # Snap to lower of the two for a believable draw scoreline
        h = a = min(h, a)
    return h, a
