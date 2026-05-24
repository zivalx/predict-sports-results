"""Run N independent tournament simulations and aggregate per-team probabilities.

Given 12 groups (each a list of 4 team handles) + a rating lookup, this:
  for i in range(N):
    - simulate all 12 groups → 12 ordered standings + per-team stats
    - rank 3rd-placed teams across groups by points/GD/GF; pick top 8
    - seed 32-team bracket using the FIFA WC 2026 official bracket template
    - simulate knockout following template-defined R16/QF/SF/F pairings
    - tally champion / runner-up / semifinalist / top-of-group counts
    - track per-team rounds reached to compute expected matches played
    - [optional] sample top-scorer goals per watchlist player, identify winner

Returns a SimulationResult that exposes `p_champion(team)`, `p_runner_up(team)`,
`p_semi(team)`, `p_top_group(team)`, `expected_matches_played(team)`,
and optionally `p_top_scorer(player)`, `expected_goals(player)`.
"""

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from worldcap.model.simulator.bracket import simulate_knockout
from worldcap.model.simulator.bracket_template import (
    WC2026_R32,
    assign_third_place_slots,
)
from worldcap.model.simulator.group_stage import simulate_group
from worldcap.model.simulator.top_scorer import PlayerEntry, sample_iteration_top_scorer


# Per-team matches played by round reached.
# "group" = didn't reach R32 (3 matches)
# "R32" = lost in R32 (4 matches: 3 group + 1 R32)
# "R16" = lost in R16 (5 matches)
# ... etc ...
# "F" = reached final, won or lost (8 matches: 3 group + R32 + R16 + QF + SF + F)
# "champion" = won final (8 matches)
_MATCHES_PER_ROUND = {
    "group": 3,
    "R32": 4,
    "R16": 5,
    "QF": 6,
    "SF": 7,
    "F": 8,
    "champion": 8,
}

# Group labels for WC 2026 (12 groups A–L).
_GROUP_LABELS = list("ABCDEFGHIJKL")


@dataclass
class SimulationResult:
    n_iterations: int
    _champion_counts: Counter = field(default_factory=Counter)
    _runner_up_counts: Counter = field(default_factory=Counter)
    _semi_counts: Counter = field(default_factory=Counter)
    _top_group_counts: Counter = field(default_factory=Counter)
    # Sum of "matches played in this iteration" per team across iterations.
    _matches_played_total: dict = field(default_factory=lambda: defaultdict(int))
    # Top-scorer tracking: winner counts and total goals per player
    _top_scorer_counts: Counter = field(default_factory=Counter)
    _goals_total: dict = field(default_factory=lambda: defaultdict(int))

    def p_champion(self, team: Any) -> float:
        return self._champion_counts.get(team, 0) / self.n_iterations

    def p_runner_up(self, team: Any) -> float:
        return self._runner_up_counts.get(team, 0) / self.n_iterations

    def p_semi(self, team: Any) -> float:
        return self._semi_counts.get(team, 0) / self.n_iterations

    def p_top_group(self, team: Any) -> float:
        return self._top_group_counts.get(team, 0) / self.n_iterations

    def expected_matches_played(self, team: Any) -> float:
        """Mean tournament matches played across iterations."""
        return self._matches_played_total.get(team, 0) / self.n_iterations

    def p_top_scorer(self, player: Any) -> float:
        """Probability a player wins the Golden Boot across all iterations."""
        return self._top_scorer_counts.get(player, 0) / self.n_iterations

    def expected_goals(self, player: Any) -> float:
        """Mean tournament goals across all iterations."""
        return self._goals_total.get(player, 0) / self.n_iterations


def _rank_third_placed(
    third_teams: list[Any],
    standings_maps: list[dict],
    rng: random.Random,
    k: int = 8,
) -> list[Any]:
    """Rank the 12 third-placed teams and return the best k.

    Ranking criteria (FIFA WC 2026):
      1. Points
      2. Goal difference
      3. Goals scored
      4. Random lots (drawn by lots — we use rng for determinism)

    third_teams: list of 12 third-placed team handles (one per group)
    standings_maps: list of 12 dicts (one per group), each mapping team → _Standing
    """
    stats = []
    for team, smap in zip(third_teams, standings_maps):
        s = smap[team]
        stats.append((team, s.points, s.gd, s.gf, rng.random()))

    # Sort descending by (points, gd, gf), then ascending random for lots
    stats.sort(key=lambda x: (-x[1], -x[2], -x[3], x[4]))
    return [x[0] for x in stats[:k]]


def _seed_bracket_from_template(
    group_standings: list[list[Any]],
    third_slot_map: dict[str, Any],
) -> list[Any]:
    """Build the 32-team seeded list from the FIFA bracket template.

    Maps each slot in WC2026_R32 to an actual team, then returns a flat list
    of 32 teams arranged so that seeded_teams[2*i] and seeded_teams[2*i+1]
    are the (left, right) teams for R32 match i.

    group_standings: list of 12 ordered standings, groups A–L (index 0–11).
    third_slot_map: {"3RD_1": team, ..., "3RD_8": team} from assign_third_place_slots.
    """
    # Build slot → team lookup
    slot_map: dict[str, Any] = {}
    for i, label in enumerate(_GROUP_LABELS):
        standings = group_standings[i]
        slot_map[f"{label}1"] = standings[0]  # winner
        slot_map[f"{label}2"] = standings[1]  # runner-up

    slot_map.update(third_slot_map)

    seeded: list[Any] = []
    for left_slot, right_slot in WC2026_R32:
        seeded.append(slot_map[left_slot])
        seeded.append(slot_map[right_slot])

    if len(seeded) != 32:
        raise ValueError(f"Bracket seeding produced {len(seeded)} teams; expected 32")

    return seeded


def simulate_tournament(
    groups: list[list[Any]],
    ratings_by_team: dict[Any, float],
    n_iterations: int = 10_000,
    seed: Optional[int] = None,
    players: Optional[list[PlayerEntry]] = None,
) -> SimulationResult:
    """Run N iterations and aggregate per-team probabilities."""
    if len(groups) != 12:
        raise ValueError(f"WC 2026 has 12 groups; got {len(groups)}")
    for g in groups:
        if len(g) != 4:
            raise ValueError("Each group must have exactly 4 teams")

    master_rng = random.Random(seed)
    result = SimulationResult(n_iterations=n_iterations)

    all_teams = [t for g in groups for t in g]

    for _ in range(n_iterations):
        # Fresh per-iteration rng deterministically derived from master
        iter_rng = random.Random(master_rng.random())

        # Simulate all 12 groups, collecting standings + per-team stats
        group_standings: list[list[Any]] = []
        standings_maps: list[dict] = []
        for group in groups:
            ordered, smap = simulate_group(group, ratings_by_team, rng=iter_rng)
            group_standings.append(ordered)
            standings_maps.append(smap)

        # Collect 3rd-placed teams and rank them by points/GD/GF
        third_placed = [standings[2] for standings in group_standings]
        ranked_thirds = _rank_third_placed(third_placed, standings_maps, rng=iter_rng, k=8)

        # Assign 3rd-place slots (v0: by rank order)
        third_slot_map = assign_third_place_slots(ranked_thirds)

        # Build the 32-team seeded bracket following the FIFA template
        seeded = _seed_bracket_from_template(group_standings, third_slot_map)

        ko = simulate_knockout(seeded, ratings_by_team, rng=iter_rng)
        result._champion_counts[ko["champion"]] += 1
        result._runner_up_counts[ko["runner_up"]] += 1
        for t in ko["semifinalists"]:
            result._semi_counts[t] += 1
        for standings in group_standings:
            result._top_group_counts[standings[0]] += 1

        # Per-team rounds → matches played
        rounds_reached = ko["rounds_reached"]
        team_round = {}
        for t in all_teams:
            team_round[t] = rounds_reached.get(t, "group")
            result._matches_played_total[t] += _MATCHES_PER_ROUND[team_round[t]]

        # Optional: sample top-scorer for this iteration
        if players:
            winner, goals = sample_iteration_top_scorer(players, team_round, rng=iter_rng)
            if winner is not None:
                result._top_scorer_counts[winner] += 1
            for p_handle, g in goals.items():
                result._goals_total[p_handle] += g

    return result
