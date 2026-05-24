import random
from collections import Counter

import pytest

from worldcup.model.simulator.score_sampling import sample_outcome, sample_score


def test_sample_outcome_returns_one_of_three():
    rng = random.Random(42)
    out = sample_outcome(0.4, 0.3, 0.3, rng=rng)
    assert out in ("home", "draw", "away")


def test_sample_outcome_frequencies_match_probabilities_at_scale():
    rng = random.Random(42)
    counts = Counter()
    n = 50_000
    for _ in range(n):
        counts[sample_outcome(0.5, 0.3, 0.2, rng=rng)] += 1
    # Each frequency within 1pp of the expected probability
    assert abs(counts["home"] / n - 0.5) < 0.01
    assert abs(counts["draw"] / n - 0.3) < 0.01
    assert abs(counts["away"] / n - 0.2) < 0.01


def test_sample_outcome_is_deterministic_under_seeded_rng():
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    seq1 = [sample_outcome(0.4, 0.3, 0.3, rng=rng1) for _ in range(20)]
    seq2 = [sample_outcome(0.4, 0.3, 0.3, rng=rng2) for _ in range(20)]
    assert seq1 == seq2


def test_sample_score_home_win_has_home_higher():
    rng = random.Random(42)
    for _ in range(50):
        h, a = sample_score("home", home_strength=1.6, away_strength=1.0, rng=rng)
        assert h > a
        assert h >= 1
        assert a >= 0


def test_sample_score_away_win_has_away_higher():
    rng = random.Random(42)
    for _ in range(50):
        h, a = sample_score("away", home_strength=1.0, away_strength=1.6, rng=rng)
        assert a > h
        assert a >= 1
        assert h >= 0


def test_sample_score_draw_is_equal():
    rng = random.Random(42)
    for _ in range(50):
        h, a = sample_score("draw", home_strength=1.2, away_strength=1.2, rng=rng)
        assert h == a
        assert h >= 0


def test_sample_score_invalid_outcome_raises():
    rng = random.Random(42)
    with pytest.raises(ValueError):
        sample_score("garbage", 1.0, 1.0, rng=rng)
