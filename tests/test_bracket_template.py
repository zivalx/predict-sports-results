"""Tests for the FIFA WC 2026 bracket template and updated simulator."""

import random
from dataclasses import dataclass

import pytest

from worldcup.model.simulator.bracket_template import (
    WC2026_F_FROM_SF,
    WC2026_QF_FROM_R16,
    WC2026_R16_FROM_R32,
    WC2026_R32,
    WC2026_SF_FROM_QF,
    assign_third_place_slots,
)
from worldcup.model.simulator.orchestrator import SimulationResult, simulate_tournament


@dataclass(frozen=True)
class T:
    id: int


# ---------------------------------------------------------------------------
# Structural tests for the bracket template
# ---------------------------------------------------------------------------

def test_r32_has_exactly_16_entries():
    assert len(WC2026_R32) == 16


def test_r32_entries_are_2_tuples():
    for entry in WC2026_R32:
        assert len(entry) == 2, f"Expected 2-tuple, got {entry}"


def test_r16_has_exactly_8_entries():
    assert len(WC2026_R16_FROM_R32) == 8


def test_r16_references_each_r32_index_exactly_once():
    """Every R32 match index 0..15 appears exactly once across R16 pairings."""
    referenced = []
    for left, right in WC2026_R16_FROM_R32:
        referenced.append(left)
        referenced.append(right)
    assert sorted(referenced) == list(range(16)), (
        f"R16 pairings do not cover R32 indices 0-15 exactly once: {sorted(referenced)}"
    )


def test_qf_has_exactly_4_entries():
    assert len(WC2026_QF_FROM_R16) == 4


def test_qf_references_each_r16_index_exactly_once():
    """Every R16 match index 0..7 appears exactly once across QF pairings."""
    referenced = []
    for left, right in WC2026_QF_FROM_R16:
        referenced.append(left)
        referenced.append(right)
    assert sorted(referenced) == list(range(8)), (
        f"QF pairings do not cover R16 indices 0-7 exactly once: {sorted(referenced)}"
    )


def test_sf_has_exactly_2_entries():
    assert len(WC2026_SF_FROM_QF) == 2


def test_sf_references_each_qf_index_exactly_once():
    referenced = []
    for left, right in WC2026_SF_FROM_QF:
        referenced.append(left)
        referenced.append(right)
    assert sorted(referenced) == list(range(4)), (
        f"SF pairings do not cover QF indices 0-3 exactly once: {sorted(referenced)}"
    )


def test_final_is_a_pair_of_sf_indices():
    left, right = WC2026_F_FROM_SF
    assert left in range(2)
    assert right in range(2)
    assert left != right


def test_r32_slots_cover_all_12_group_winners_and_runners_up():
    """Every group A-L should appear exactly once as winner and once as runner-up."""
    from string import ascii_uppercase
    groups = list(ascii_uppercase[:12])  # A through L

    winners = set()
    runners_up = set()

    for left, right in WC2026_R32:
        for slot in (left, right):
            if slot.startswith("3RD_"):
                continue  # third-place slots are handled separately
            # Slot is like "A1" or "B2" — letter then digit
            group_letter = slot[:-1]  # all but last char (the digit)
            rank_digit = slot[-1]
            if rank_digit == "1":
                winners.add(group_letter)
            elif rank_digit == "2":
                runners_up.add(group_letter)

    assert winners == set(groups), f"Missing/extra group winners: {winners}"
    assert runners_up == set(groups), f"Missing/extra group runners-up: {runners_up}"


def test_r32_has_exactly_8_third_place_slots():
    third_slots = [
        slot
        for left, right in WC2026_R32
        for slot in (left, right)
        if slot.startswith("3RD_")
    ]
    assert len(third_slots) == 8
    # They should be 3RD_1 through 3RD_8
    assert sorted(third_slots) == [f"3RD_{i}" for i in range(1, 9)]


# ---------------------------------------------------------------------------
# assign_third_place_slots
# ---------------------------------------------------------------------------

def test_assign_third_place_slots_returns_8_keys():
    teams = [T(i) for i in range(8)]
    result = assign_third_place_slots(teams)
    assert len(result) == 8
    assert set(result.keys()) == {f"3RD_{i}" for i in range(1, 9)}


def test_assign_third_place_slots_preserves_rank_order():
    teams = [T(i) for i in range(8)]
    result = assign_third_place_slots(teams)
    for i, team in enumerate(teams):
        assert result[f"3RD_{i + 1}"] == team


def test_assign_third_place_slots_raises_on_wrong_count():
    with pytest.raises(ValueError):
        assign_third_place_slots([T(i) for i in range(7)])
    with pytest.raises(ValueError):
        assign_third_place_slots([T(i) for i in range(9)])


# ---------------------------------------------------------------------------
# Full tournament simulation tests (with new structured bracket)
# ---------------------------------------------------------------------------

def _wc_groups():
    """12 groups of 4 teams = 48 teams, IDs 0..47."""
    teams = [T(i) for i in range(48)]
    groups = [teams[i:i + 4] for i in range(0, 48, 4)]
    return groups, teams


def test_simulate_tournament_p_champion_sums_to_one():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=500, seed=42)
    total = sum(result.p_champion(t) for t in teams)
    assert total == pytest.approx(1.0, abs=1e-9)


def test_simulate_tournament_dominant_team_wins_most():
    groups, teams = _wc_groups()
    ratings = {t: 1400.0 for t in teams}
    dominant = teams[0]
    ratings[dominant] = 2200.0

    result = simulate_tournament(groups, ratings, n_iterations=500, seed=42)
    assert result.p_champion(dominant) > 0.3
    assert result.p_top_group(dominant) > 0.85
    assert result.p_semi(dominant) > 0.7


def test_simulate_tournament_deterministic_under_same_seed():
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    r1 = simulate_tournament(groups, ratings, n_iterations=200, seed=7)
    r2 = simulate_tournament(groups, ratings, n_iterations=200, seed=7)
    for t in teams:
        assert r1.p_champion(t) == r2.p_champion(t)


def test_simulate_tournament_p_semi_sum_equals_four():
    """Exactly 4 semifinalists per iteration → sum of p_semi == 4.0."""
    groups, teams = _wc_groups()
    ratings = {t: 1500.0 for t in teams}
    result = simulate_tournament(groups, ratings, n_iterations=300, seed=42)
    total_semi = sum(result.p_semi(t) for t in teams)
    assert total_semi == pytest.approx(4.0, abs=1e-9)
