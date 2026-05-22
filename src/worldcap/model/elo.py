"""Elo rating system.

Pure functions, no DB. Persistence and orchestration handled by callers.

Conventions:
- Ratings are floats. Higher is better.
- A home-team advantage of HOME_ADVANTAGE points is added to home rating
  when computing expected score.
- Result: 1.0 = home win, 0.5 = draw, 0.0 = away win.
- K-factor scales by tournament stage (later rounds matter more).
"""

INITIAL_RATING = 1500.0
HOME_ADVANTAGE = 100.0
K_BASE = 32.0

_K_BY_STAGE = {
    "group": 32.0,
    "R32": 48.0,
    "R16": 56.0,
    "QF": 64.0,
    "SF": 72.0,
    "F": 80.0,
    "3rd": 56.0,
}


def expected_score(home_rating: float, away_rating: float) -> float:
    """Probability the home team wins (or, for the purpose of Elo update, the
    expected score in [0, 1]) given current ratings, with home advantage applied."""
    diff = (away_rating - (home_rating + HOME_ADVANTAGE)) / 400.0
    return 1.0 / (1.0 + 10.0 ** diff)


def k_factor(stage: str) -> float:
    """K-factor for a given stage. Unknown stages fall back to K_BASE."""
    return _K_BY_STAGE.get(stage, K_BASE)


def update_ratings(
    home_rating: float,
    away_rating: float,
    *,
    result: float,
    stage: str,
) -> tuple[float, float]:
    """Apply an Elo update for one completed match.

    Returns (new_home_rating, new_away_rating).
    Raises ValueError if result is not in {0.0, 0.5, 1.0}.
    """
    if result not in (0.0, 0.5, 1.0):
        raise ValueError(f"result must be 0.0, 0.5, or 1.0; got {result}")

    e_home = expected_score(home_rating, away_rating)
    k = k_factor(stage)
    delta = k * (result - e_home)
    return (home_rating + delta, away_rating - delta)
