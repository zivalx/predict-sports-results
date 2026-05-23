import random
from dataclasses import dataclass

import pytest

from worldcap.model.simulator.bracket import simulate_knockout


@dataclass(frozen=True)
class T:
    id: int


def _seeded_32():
    return [T(i) for i in range(32)]


def test_knockout_returns_champion_runner_up_and_semifinalists():
    teams = _seeded_32()
    ratings = {t: 1500.0 for t in teams}
    rng = random.Random(42)
    result = simulate_knockout(teams, ratings, rng=rng)
    assert "champion" in result
    assert "runner_up" in result
    assert "semifinalists" in result
    assert result["champion"] in teams
    assert result["runner_up"] in teams
    assert result["champion"] != result["runner_up"]
    assert len(result["semifinalists"]) == 4
    assert result["champion"] in result["semifinalists"]
    assert result["runner_up"] in result["semifinalists"]


def test_knockout_deterministic_under_seeded_rng():
    teams = _seeded_32()
    ratings = {t: 1500.0 for t in teams}
    rng1 = random.Random(7)
    rng2 = random.Random(7)
    assert simulate_knockout(teams, ratings, rng=rng1) == simulate_knockout(teams, ratings, rng=rng2)


def test_knockout_strong_team_usually_wins():
    teams = _seeded_32()
    # T0 is dominant. Everyone else is uniformly mid.
    ratings = {teams[0]: 2200.0, **{t: 1400.0 for t in teams[1:]}}
    wins = 0
    n = 500
    for i in range(n):
        result = simulate_knockout(teams, ratings, rng=random.Random(i))
        if result["champion"] == teams[0]:
            wins += 1
    assert wins / n > 0.5  # massive favourite wins majority


def test_knockout_requires_32_teams():
    teams = [T(i) for i in range(16)]
    ratings = {t: 1500.0 for t in teams}
    with pytest.raises(ValueError):
        simulate_knockout(teams, {}, rng=random.Random(0))
