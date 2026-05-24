"""Resolve a 4-team group standings using FIFA tiebreaker rules.

Order applied:
1. Points (3 win / 1 draw / 0 loss)
2. Goal difference across all group matches
3. Goals scored across all group matches
4. Random lots (steps 4-7 of the FIFA order — head-to-head and fair play —
   are deferred for v0 since they affect a minority of scenarios)

Pure function: caller passes the 6 match results + an `rng` for the lots step.
Returns the 4 teams in finishing order (winner first).
"""

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GroupMatch:
    home: Any           # opaque Team handle — identity is all that matters
    away: Any
    home_goals: int
    away_goals: int


@dataclass
class _Standing:
    team: Any
    points: int = 0
    gd: int = 0
    gf: int = 0


def _compute_standings(matches: list[GroupMatch]) -> dict[Any, _Standing]:
    """Aggregate per-team points/GD/GF from a list of match results."""
    rows: dict[Any, _Standing] = {}
    for m in matches:
        rows.setdefault(m.home, _Standing(team=m.home))
        rows.setdefault(m.away, _Standing(team=m.away))
        h, a = rows[m.home], rows[m.away]
        h.gf += m.home_goals
        a.gf += m.away_goals
        h.gd += m.home_goals - m.away_goals
        a.gd += m.away_goals - m.home_goals
        if m.home_goals > m.away_goals:
            h.points += 3
        elif m.home_goals < m.away_goals:
            a.points += 3
        else:
            h.points += 1
            a.points += 1
    return rows


def resolve_standings(matches: list[GroupMatch], *, rng: random.Random) -> tuple[list[Any], dict]:
    """Return (ordered_teams, standings_map).

    ordered_teams: the 4 teams in finishing order (winner first).
        Tie-broken first by points, then GD, then GF, then random lots.
    standings_map: dict mapping each team → its _Standing (points, gd, gf).
    """
    rows_dict = _compute_standings(matches)
    rows = list(rows_dict.values())
    # Stable sort by primary keys; equal-key ties get resolved by lots.
    # We achieve "lots" by attaching a random tag to each row before sorting,
    # so equal-key teams get a stable random ordering.
    tagged = [(r, rng.random()) for r in rows]
    tagged.sort(key=lambda t: (-t[0].points, -t[0].gd, -t[0].gf, t[1]))
    ordered_teams = [t[0].team for t in tagged]
    standings_map = {s.team: s for s in rows_dict.values()}
    return ordered_teams, standings_map
