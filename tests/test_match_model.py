import pytest

from worldcup.model.match import blend_with_market, match_probabilities


def _normalised(d: dict[str, float]) -> bool:
    return abs(sum(d.values()) - 1.0) < 1e-9


def test_match_probabilities_sums_to_one():
    p = match_probabilities(1500.0, 1500.0)
    assert _normalised(p)
    assert set(p.keys()) == {"home", "draw", "away"}


def test_match_probabilities_equal_teams_neutral_venue():
    """Equal teams at neutral venue: draw near peak, home/away split evenly."""
    p = match_probabilities(1500.0, 1500.0, home_advantage=0.0)
    assert p["draw"] == pytest.approx(0.28, abs=1e-9)  # DRAW_PEAK
    # Remaining (1 - 0.28) split evenly between home and away at equal ratings
    assert p["home"] == pytest.approx(0.36, abs=1e-9)
    assert p["away"] == pytest.approx(0.36, abs=1e-9)


def test_match_probabilities_home_advantage_skews_home():
    p_neutral = match_probabilities(1500.0, 1500.0, home_advantage=0.0)
    p_home = match_probabilities(1500.0, 1500.0, home_advantage=100.0)
    assert p_home["home"] > p_neutral["home"]
    assert p_home["away"] < p_neutral["away"]
    assert _normalised(p_home)


def test_match_probabilities_higher_rating_wins_more():
    p = match_probabilities(1800.0, 1500.0, home_advantage=0.0)
    assert p["home"] > p["away"]
    assert _normalised(p)


def test_draw_pct_higher_for_equal_teams_than_mismatch():
    """Equal teams should draw more often than a lopsided matchup."""
    p_equal = match_probabilities(1500.0, 1500.0, home_advantage=0.0)
    p_mismatch = match_probabilities(1800.0, 1500.0, home_advantage=0.0)
    assert p_equal["draw"] > p_mismatch["draw"]


def test_draw_pct_symmetric_regardless_of_who_is_stronger():
    """Draw probability depends on the gap magnitude, not direction."""
    p1 = match_probabilities(1800.0, 1500.0, home_advantage=0.0)
    p2 = match_probabilities(1500.0, 1800.0, home_advantage=0.0)
    assert p1["draw"] == pytest.approx(p2["draw"], abs=1e-9)


def test_explicit_draw_pct_overrides_auto_compute():
    """Passing draw_pct explicitly should bypass the Gaussian decay."""
    p = match_probabilities(1500.0, 1500.0, home_advantage=0.0, draw_pct=0.20)
    assert p["draw"] == pytest.approx(0.20, abs=1e-9)


def test_draw_pct_floor_for_extreme_mismatch():
    """A 500+ Elo gap should have draw rate near the floor (~10%)."""
    p = match_probabilities(2000.0, 1500.0, home_advantage=0.0)
    assert 0.08 <= p["draw"] <= 0.14


def test_draw_pct_moderate_gap_between_peak_and_floor():
    """A 200-point gap should have draw rate between floor and peak."""
    p = match_probabilities(1700.0, 1500.0, home_advantage=0.0)
    p_equal = match_probabilities(1500.0, 1500.0, home_advantage=0.0)
    p_extreme = match_probabilities(2000.0, 1500.0, home_advantage=0.0)
    assert p_extreme["draw"] < p["draw"] < p_equal["draw"]


def test_knockout_draw_pct_zero_still_works():
    """Knockout matches explicitly pass draw_pct=0.0 — must still work."""
    p = match_probabilities(1600.0, 1500.0, home_advantage=0.0, draw_pct=0.0)
    assert p["draw"] == 0.0
    assert abs(p["home"] + p["away"] - 1.0) < 1e-9


def test_blend_with_market_falls_back_when_market_none():
    model_p = {"home": 0.5, "draw": 0.25, "away": 0.25}
    out = blend_with_market(model_p, None)
    assert out == model_p


def test_blend_with_market_alpha_30():
    model_p = {"home": 0.6, "draw": 0.2, "away": 0.2}
    market_p = {"home": 0.4, "draw": 0.3, "away": 0.3}
    out = blend_with_market(model_p, market_p, alpha=0.3)
    # out = 0.3 * model + 0.7 * market
    assert out["home"] == pytest.approx(0.3 * 0.6 + 0.7 * 0.4, abs=1e-9)
    assert out["draw"] == pytest.approx(0.3 * 0.2 + 0.7 * 0.3, abs=1e-9)
    assert out["away"] == pytest.approx(0.3 * 0.2 + 0.7 * 0.3, abs=1e-9)
    assert _normalised(out)


def test_blend_preserves_sum_to_one_when_market_unnormalised():
    model_p = {"home": 0.5, "draw": 0.25, "away": 0.25}
    market_p = {"home": 0.5, "draw": 0.3, "away": 0.3}  # sums to 1.1 (vig)
    out = blend_with_market(model_p, market_p, alpha=0.3)
    assert _normalised(out)
