import pytest

from worldcup.model.elo import (
    INITIAL_RATING,
    K_BASE,
    expected_score,
    k_factor,
    update_ratings,
)


def test_expected_score_equal_ratings_is_half():
    # No home advantage in expected_score — pure Elo, equal ratings → 0.5
    assert expected_score(1500.0, 1500.0) == pytest.approx(0.5, abs=1e-9)


def test_expected_score_complementary():
    a = expected_score(1700.0, 1500.0)
    b = expected_score(1500.0, 1700.0)
    assert a + b == pytest.approx(1.0, abs=1e-9)


def test_expected_score_higher_rating_wins_more():
    assert expected_score(1800.0, 1500.0) > expected_score(1600.0, 1500.0)


def test_k_factor_increases_with_stage():
    assert k_factor("group") < k_factor("R16")
    assert k_factor("R16") < k_factor("QF")
    assert k_factor("QF") < k_factor("SF")
    assert k_factor("SF") < k_factor("F")
    # Unknown stage defaults to K_BASE
    assert k_factor("unknown") == K_BASE


def test_update_symmetric_for_draw():
    # Equal ratings, draw → no change (after home advantage washes out — actually a draw with
    # home advantage means the home team underperformed expectation slightly)
    home_r, away_r = update_ratings(1500.0, 1500.0, result=0.5, stage="group")
    # Home was expected to win > 0.5 due to home advantage, so a draw is a slight underperformance
    assert home_r < 1500.0
    assert away_r > 1500.0
    # Symmetric: home loses what away gains
    assert (1500.0 - home_r) == pytest.approx(away_r - 1500.0, abs=1e-9)


def test_update_home_win():
    home_r, away_r = update_ratings(1500.0, 1500.0, result=1.0, stage="group")
    assert home_r > 1500.0
    assert away_r < 1500.0
    # Conservation: delta_home + delta_away = 0
    assert (home_r - 1500.0) == pytest.approx(1500.0 - away_r, abs=1e-9)


def test_update_uses_stage_k_factor():
    home_r1, away_r1 = update_ratings(1500.0, 1500.0, result=1.0, stage="group")
    home_r2, away_r2 = update_ratings(1500.0, 1500.0, result=1.0, stage="F")
    # Final K is larger so the rating swing is bigger
    assert (home_r2 - 1500.0) > (home_r1 - 1500.0)


def test_invalid_result_raises():
    with pytest.raises(ValueError):
        update_ratings(1500.0, 1500.0, result=2.0, stage="group")
