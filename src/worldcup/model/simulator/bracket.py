"""Simulate a single-elimination knockout bracket starting from 32 seeded teams.

The bracket follows the FIFA WC 2026 official bracket template defined in
`bracket_template.py`. Rather than consuming teams pairwise, the bracket is
resolved by following the WC2026_R16_FROM_R32 / WC2026_QF_FROM_R16 /
WC2026_SF_FROM_QF / WC2026_F_FROM_SF connection tables.

Knockout matches use match_probabilities with home_advantage=0 (treating all
knockouts as neutral venues). On a sampled draw, a coin flip picks the advancer
— v0 simplification in lieu of an extra-time / penalties model.

Returns:
    {
        "champion": Team,
        "runner_up": Team,
        "semifinalists": list[Team],  # 4 teams who reached the SF (incl. finalists)
        "rounds_reached": dict[Team, str],  # max round reached per team
    }
"""

import random
from typing import Any

from worldcup.model.match import match_probabilities
from worldcup.model.simulator.bracket_template import (
    WC2026_F_FROM_SF,
    WC2026_QF_FROM_R16,
    WC2026_R16_FROM_R32,
    WC2026_SF_FROM_QF,
)
from worldcup.model.simulator.score_sampling import sample_outcome


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


def _play_structured_round(
    participants: list[Any],
    pairings: list[tuple[int, int]],
    ratings: dict[Any, float],
    rng: random.Random,
) -> list[Any]:
    """Play a structured knockout round given explicit pairings.

    participants: list of teams competing in this round (indexable by the
        indices referenced in `pairings`).
    pairings: list of (left_idx, right_idx) pairs referencing positions in
        the *previous* round's winner list.
    Returns: list of winners in pairing order.
    """
    winners: list[Any] = []
    for left_idx, right_idx in pairings:
        winner = _play_knockout_match(participants[left_idx], participants[right_idx], ratings, rng)
        winners.append(winner)
    return winners


def simulate_knockout(
    seeded_teams: list[Any],
    ratings_by_team: dict[Any, float],
    *,
    rng: random.Random,
) -> dict:
    """Simulate R32 → F following the FIFA WC 2026 bracket template.

    seeded_teams: 32 teams in slot order matching WC2026_R32.  Each pair
        (seeded_teams[2*i], seeded_teams[2*i+1]) is the (left, right) team
        for R32 match index i.

    Returns a dict with keys champion, runner_up, semifinalists, rounds_reached.
    """
    if len(seeded_teams) != BRACKET_R32_TEAMS:
        raise ValueError(
            f"simulate_knockout requires exactly {BRACKET_R32_TEAMS} teams; got {len(seeded_teams)}"
        )

    # Initialize: all seeded teams reach at least R32
    rounds_reached: dict = {t: "R32" for t in seeded_teams}

    # --- R32 → 16 winners ---
    # Play each of the 16 R32 matches (pairs of consecutive teams in seeded_teams)
    r32_winners: list[Any] = []
    for i in range(16):
        left = seeded_teams[2 * i]
        right = seeded_teams[2 * i + 1]
        winner = _play_knockout_match(left, right, ratings_by_team, rng)
        r32_winners.append(winner)

    for t in r32_winners:
        rounds_reached[t] = "R16"

    # --- R16 → 8 winners (structured pairings) ---
    r16_winners = _play_structured_round(r32_winners, WC2026_R16_FROM_R32, ratings_by_team, rng)
    for t in r16_winners:
        rounds_reached[t] = "QF"

    # --- QF → 4 winners ---
    qf_winners = _play_structured_round(r16_winners, WC2026_QF_FROM_R16, ratings_by_team, rng)
    for t in qf_winners:
        rounds_reached[t] = "SF"
    semifinalists = list(qf_winners)  # capture before the final round

    # --- SF → 2 finalists ---
    sf_winners = _play_structured_round(qf_winners, WC2026_SF_FROM_QF, ratings_by_team, rng)
    for t in sf_winners:
        rounds_reached[t] = "F"

    # --- Final ---
    sf_left_idx, sf_right_idx = WC2026_F_FROM_SF
    finalist_left = sf_winners[sf_left_idx]
    finalist_right = sf_winners[sf_right_idx]
    champion = _play_knockout_match(finalist_left, finalist_right, ratings_by_team, rng)
    runner_up = finalist_right if champion == finalist_left else finalist_left
    rounds_reached[champion] = "champion"
    # runner_up stays at "F"

    return {
        "champion": champion,
        "runner_up": runner_up,
        "semifinalists": semifinalists,
        "rounds_reached": rounds_reached,
    }
