"""3-way match outcome model.

Pure functions. Translates Elo ratings into (p_home, p_draw, p_away) and
optionally blends with a market source.
"""

from worldcup.model.elo import HOME_ADVANTAGE, expected_score


DEFAULT_DRAW_PCT = 0.27  # empirical World Cup draw rate (regulation time)
DEFAULT_ALPHA = 0.3       # weight on the model when blending with the market


def match_probabilities(
    home_rating: float,
    away_rating: float,
    *,
    draw_pct: float = DEFAULT_DRAW_PCT,
    home_advantage: float = HOME_ADVANTAGE,
) -> dict[str, float]:
    """Return {"home": p, "draw": p, "away": p} that sums to 1.

    Approach: a fixed draw bucket (draw_pct) plus an Elo-derived split of the
    remaining mass between home and away. Home advantage is applied as an Elo
    offset before computing expected_score.
    """
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
