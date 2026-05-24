import random
from dataclasses import dataclass

import pytest

from worldcup.model.simulator.orchestrator import simulate_tournament
from worldcup.model.simulator.top_scorer import (
    PlayerEntry,
    sample_iteration_top_scorer,
)


@dataclass(frozen=True)
class T:
    id: int


@dataclass(frozen=True)
class P:
    id: int


def test_sample_iteration_returns_winner_and_goals():
    pa = PlayerEntry(player_handle=P(1), team=T(1), goals_per_90=0.5, start_prob=1.0)
    pb = PlayerEntry(player_handle=P(2), team=T(2), goals_per_90=0.5, start_prob=1.0)
    rng = random.Random(42)
    winner, goals = sample_iteration_top_scorer(
        [pa, pb],
        team_round_this_iter={T(1): "group", T(2): "champion"},
        rng=rng,
    )
    assert winner in (P(1), P(2))
    assert P(1) in goals and P(2) in goals


def test_sample_iteration_no_players_returns_none():
    rng = random.Random(42)
    winner, goals = sample_iteration_top_scorer([], {}, rng=rng)
    assert winner is None
    assert goals == {}


def test_dominant_scorer_on_champion_team_usually_tops_race():
    # 12-group WC simulation; one player far above the rest.
    teams = [T(i) for i in range(48)]
    groups = [teams[i:i + 4] for i in range(0, 48, 4)]
    ratings = {t: 1500.0 for t in teams}
    ratings[teams[0]] = 2200.0  # T(0) is the dominant team

    dominant = PlayerEntry(player_handle=P(99), team=teams[0], goals_per_90=1.5, start_prob=1.0)
    others = [
        PlayerEntry(player_handle=P(i), team=teams[i % 48], goals_per_90=0.4, start_prob=1.0)
        for i in range(20)
    ]
    players = [dominant] + others

    result = simulate_tournament(
        groups, ratings, n_iterations=500, seed=42, players=players,
    )
    p_dominant = result.p_top_scorer(P(99))
    assert p_dominant > 0.4  # dominant scorer on dominant team
    assert result.expected_goals(P(99)) > result.expected_goals(P(0))


def test_simulate_tournament_without_players_doesnt_break():
    teams = [T(i) for i in range(48)]
    groups = [teams[i:i + 4] for i in range(0, 48, 4)]
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=100, seed=42)
    # No players provided → top-scorer counters empty
    assert result.p_top_scorer(P(0)) == 0.0
    assert result.expected_goals(P(0)) == 0.0
