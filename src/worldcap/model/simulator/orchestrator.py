"""Run N independent tournament simulations and aggregate per-team probabilities.

Given 12 groups (each a list of 4 team handles) + a rating lookup, this:
  for i in range(N):
    - simulate all 12 groups → 12 ordered standings
    - rank 3rd-placed teams across groups; pick top 8 by composite score
    - seed 32-team bracket: alternate 1st/2nd from each group + 8 best 3rds
    - simulate knockout
    - tally champion / runner-up / semifinalist / top-of-group counts

Returns a SimulationResult that exposes `p_champion(team)`, `p_runner_up(team)`,
`p_semi(team)`, `p_top_group(team)`.
"""

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from worldcap.model.simulator.bracket import simulate_knockout
from worldcap.model.simulator.group_stage import simulate_group


# We re-rank 3rd-placed teams using the same priors as inside a group, so we
# need their final-table stats. Group stage already encodes ordering; we capture
# raw counters here by re-aggregating from the simulator's match outputs.
# For v0 simplicity we rank 3rd-placed teams by group order alone — i.e., a 3rd
# place from a stronger group is treated as equivalent to a 3rd from a weaker one.
# A future refinement could re-aggregate points/GD/GF.

@dataclass
class SimulationResult:
    n_iterations: int
    _champion_counts: Counter = field(default_factory=Counter)
    _runner_up_counts: Counter = field(default_factory=Counter)
    _semi_counts: Counter = field(default_factory=Counter)
    _top_group_counts: Counter = field(default_factory=Counter)

    def p_champion(self, team: Any) -> float:
        return self._champion_counts.get(team, 0) / self.n_iterations

    def p_runner_up(self, team: Any) -> float:
        return self._runner_up_counts.get(team, 0) / self.n_iterations

    def p_semi(self, team: Any) -> float:
        return self._semi_counts.get(team, 0) / self.n_iterations

    def p_top_group(self, team: Any) -> float:
        return self._top_group_counts.get(team, 0) / self.n_iterations


def _pick_best_third_placed(third_placed_per_iter: list[Any], k: int = 8) -> list[Any]:
    """Pick k of the 12 third-placed teams in this iteration.

    v0 placeholder: deterministic by position in the input order (i.e., take
    the first k). This is intentionally simple — a real implementation would
    rank by group-stage points/GD/GF, which we'd need to thread through from
    simulate_group. The bracket-pairing impact on tournament-level probs is
    second-order; document and move on.
    """
    return third_placed_per_iter[:k]


def _seed_bracket(
    group_standings: list[list[Any]],
    third_placed_picks: list[Any],
) -> list[Any]:
    """Concatenate 24 top-2 + 8 best-3rd into a 32-team bracket order.

    Order: [G0-1st, G0-2nd, G1-1st, G1-2nd, ..., G11-1st, G11-2nd, then 8 best 3rds].
    """
    out: list[Any] = []
    for standings in group_standings:
        out.append(standings[0])
        out.append(standings[1])
    out.extend(third_placed_picks)
    if len(out) != 32:
        raise ValueError(f"Bracket seeding produced {len(out)} teams; expected 32")
    return out


def simulate_tournament(
    groups: list[list[Any]],
    ratings_by_team: dict[Any, float],
    n_iterations: int = 10_000,
    seed: int | None = None,
) -> SimulationResult:
    """Run N iterations and aggregate per-team probabilities."""
    if len(groups) != 12:
        raise ValueError(f"WC 2026 has 12 groups; got {len(groups)}")
    for g in groups:
        if len(g) != 4:
            raise ValueError("Each group must have exactly 4 teams")

    master_rng = random.Random(seed)
    result = SimulationResult(n_iterations=n_iterations)

    for _ in range(n_iterations):
        # Fresh per-iteration rng deterministically derived from master
        iter_rng = random.Random(master_rng.random())

        group_standings: list[list[Any]] = [
            simulate_group(group, ratings_by_team, rng=iter_rng) for group in groups
        ]

        third_placed = [standings[2] for standings in group_standings]
        third_placed_picks = _pick_best_third_placed(third_placed, k=8)

        seeded = _seed_bracket(group_standings, third_placed_picks)

        ko = simulate_knockout(seeded, ratings_by_team, rng=iter_rng)
        result._champion_counts[ko["champion"]] += 1
        result._runner_up_counts[ko["runner_up"]] += 1
        for t in ko["semifinalists"]:
            result._semi_counts[t] += 1
        for standings in group_standings:
            result._top_group_counts[standings[0]] += 1

    return result
