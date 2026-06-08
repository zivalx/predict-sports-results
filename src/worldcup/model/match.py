"""3-way match outcome model.

Pure functions. Translates Elo ratings into (p_home, p_draw, p_away) and
optionally blends with a market source.
"""

import math

from worldcup.model.elo import HOME_ADVANTAGE, expected_score


# Draw probability parameters (Gaussian decay with Elo gap)
DRAW_PEAK = 0.28      # draw rate when teams are equal
DRAW_FLOOR = 0.10     # minimum draw rate for extreme mismatches
DRAW_SCALE = 300.0    # Elo gap at which decay is ~37% of (peak - floor)

DEFAULT_ALPHA = 0.3   # weight on the model when blending with the market


def _draw_pct_from_gap(elo_gap: float) -> float:
    """Compute draw probability from absolute Elo gap.

    Gaussian decay: peak for equal teams, decaying to floor for large gaps.
    """
    return DRAW_FLOOR + (DRAW_PEAK - DRAW_FLOOR) * math.exp(
        -(elo_gap / DRAW_SCALE) ** 2
    )


def match_probabilities(
    home_rating: float,
    away_rating: float,
    *,
    draw_pct: float | None = None,
    home_advantage: float = HOME_ADVANTAGE,
) -> dict[str, float]:
    """Return {"home": p, "draw": p, "away": p} that sums to 1.

    When draw_pct is None (default), it is computed from the Elo gap using
    a Gaussian decay: ~28% for equal teams, tapering to ~10% for large gaps.
    Pass draw_pct explicitly to override (e.g. 0.0 for knockout matches).
    """
    if draw_pct is None:
        gap = abs(home_rating - away_rating)
        draw_pct = _draw_pct_from_gap(gap)
    if not (0.0 <= draw_pct < 1.0):
        raise ValueError(f"draw_pct must be in [0, 1); got {draw_pct}")
    e_home = expected_score(home_rating + home_advantage, away_rating)
    rest = 1.0 - draw_pct
    return {
        "home": rest * e_home,
        "draw": draw_pct,
        "away": rest * (1.0 - e_home),
    }


def blend_with_market(
    model_p: dict[str, float],
    market_p: dict[str, float] | None,
    *,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, float]:
    """Blend model probabilities with market probabilities.

    Returns alpha * model + (1 - alpha) * market, then renormalises so the
    output sums to 1 (markets often carry vig, i.e. sum > 1).

    If market_p is None, returns model_p unchanged.
    """
    if market_p is None:
        return dict(model_p)
    out = {
        k: alpha * model_p.get(k, 0.0) + (1.0 - alpha) * market_p.get(k, 0.0)
        for k in ("home", "draw", "away")
    }
    total = sum(out.values())
    if total <= 0:
        return dict(model_p)
    return {k: v / total for k, v in out.items()}
