import random
from collections import Counter
from dataclasses import dataclass

import pytest

from worldcap.model.simulator.group_stage import simulate_group


@dataclass(frozen=True)
class T:
    id: int


@pytest.fixture
def teams():
    return [T(1), T(2), T(3), T(4)]


def test_returns_4_teams_in_order(teams):
    ratings = {t: 1500.0 for t in teams}
    rng = random.Random(42)
    order = simulate_group(teams, ratings, rng=rng)
    assert len(order) == 4
    assert set(order) == set(teams)


def test_deterministic_under_seeded_rng(teams):
    ratings = {t: 1500.0 for t in teams}
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    assert simulate_group(teams, ratings, rng=rng1) == simulate_group(teams, ratings, rng=rng2)


def test_dominant_team_tops_group_most_of_the_time(teams):
    # T1 way stronger than the others.
    ratings = {teams[0]: 1900.0, teams[1]: 1300.0, teams[2]: 1300.0, teams[3]: 1300.0}
    top_counts = Counter()
    n = 1000
    for i in range(n):
        order = simulate_group(teams, ratings, rng=random.Random(i))
        top_counts[order[0]] += 1
    assert top_counts[teams[0]] / n > 0.85  # dominant team tops > 85% of the time


def test_raises_on_wrong_group_size(teams):
    ratings = {t: 1500.0 for t in teams}
    with pytest.raises(ValueError):
        simulate_group(teams[:3], ratings, rng=random.Random(0))
