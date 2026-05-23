import random
from dataclasses import dataclass

import pytest

from worldcap.model.simulator.orchestrator import SimulationResult, simulate_tournament


@dataclass(frozen=True)
class T:
    id: int


def _wc_groups():
    """12 groups of 4 teams = 48 teams, IDs 0..47."""
    teams = [T(i) for i in range(48)]
    groups = [teams[i:i + 4] for i in range(0, 48, 4)]
    return groups, teams


def test_result_has_all_teams_with_probabilities_summing_to_one():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=500, seed=42)
    assert isinstance(result, SimulationResult)
    total = sum(result.p_champion(t) for t in teams)
    # Monte Carlo noise on 500 iterations with 48 teams — should still sum to 1.0 exactly
    assert total == pytest.approx(1.0, abs=1e-9)


def test_deterministic_under_same_seed():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    r1 = simulate_tournament(groups, ratings, n_iterations=200, seed=7)
    r2 = simulate_tournament(groups, ratings, n_iterations=200, seed=7)
    for t in teams:
        assert r1.p_champion(t) == r2.p_champion(t)
        assert r1.p_runner_up(t) == r2.p_runner_up(t)
        assert r1.p_semi(t) == r2.p_semi(t)
        assert r1.p_top_group(t) == r2.p_top_group(t)


def test_dominant_team_has_high_championship_probability():
    groups, teams = _wc_groups()
    ratings = {t: 1400.0 for t in teams}
    dominant = teams[0]
    ratings[dominant] = 2200.0
    result = simulate_tournament(groups, ratings, n_iterations=1000, seed=42)
    assert result.p_champion(dominant) > 0.3  # massive favourite
    assert result.p_top_group(dominant) > 0.85
    assert result.p_semi(dominant) > 0.7


def test_p_top_group_sums_to_one_per_group():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=400, seed=42)
    for group in groups:
        total = sum(result.p_top_group(t) for t in group)
        assert total == pytest.approx(1.0, abs=1e-9)


def test_iterations_count_is_recorded():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=123, seed=42)
    assert result.n_iterations == 123
