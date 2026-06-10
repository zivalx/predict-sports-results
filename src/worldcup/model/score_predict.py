"""Per-match score prediction.

Runs quick Monte Carlo samples for a single match to produce a scoreline
distribution, then optionally blends with Polymarket exact-score markets
to output one consolidated predicted score.
"""

import random
from collections import Counter

from worldcup.model.elo import HOME_ADVANTAGE
from worldcup.model.match import match_probabilities
from worldcup.model.simulator.score_sampling import sample_outcome, sample_score


def _rating_to_strength(rating: float) -> float:
    """Convert Elo rating to expected-goals rate. Same as group_stage."""
    return max(0.3, 1.4 + (rating - 1500.0) / 250.0)


def simulate_score_distribution(
    home_rating: float,
    away_rating: float,
    n_samples: int = 10_000,
    seed: int | None = None,
) -> dict[tuple[int, int], float]:
    """Run n_samples and return {(home_goals, away_goals): probability}.

    Returns only scores that appeared at least once, sorted by frequency desc.
    """
    rng = random.Random(seed)
    probs = match_probabilities(home_rating, away_rating)
    home_str = _rating_to_strength(home_rating)
    away_str = _rating_to_strength(away_rating)

    counts: Counter[tuple[int, int]] = Counter()
    for _ in range(n_samples):
        outcome = sample_outcome(probs["home"], probs["draw"], probs["away"], rng=rng)
        h, a = sample_score(outcome, home_str, away_str, rng=rng)
        counts[(h, a)] += 1

    return {score: count / n_samples for score, count in counts.most_common()}


def predict_score(
    home_rating: float,
    away_rating: float,
    *,
    poly_scores: dict[tuple[int, int], float] | None = None,
    alpha: float = 0.3,
    n_samples: int = 10_000,
    seed: int | None = None,
) -> dict:
    """Return consolidated score prediction for a single match.

    Args:
        home_rating, away_rating: Elo ratings
        poly_scores: Polymarket exact-score distribution {(h,a): prob} or None
        alpha: weight on our model (1-alpha on market). Same as blend_with_market.
        n_samples: Monte Carlo samples for model distribution
        seed: RNG seed for reproducibility

    Returns:
        {
            "score": (home_goals, away_goals),
            "score_str": "2-1",
            "prob": 0.145,
            "expected_goals": 2.6,
            "top_3": [("1-0", 0.18), ("2-1", 0.12), ("0-0", 0.10)],
        }
    """
    model_dist = simulate_score_distribution(home_rating, away_rating, n_samples, seed)

    if poly_scores:
        # Blend: alpha * model + (1 - alpha) * market
        all_scores = set(model_dist.keys()) | set(poly_scores.keys())
        blended: dict[tuple[int, int], float] = {}
        for s in all_scores:
            m = model_dist.get(s, 0.0)
            p = poly_scores.get(s, 0.0)
            blended[s] = alpha * m + (1 - alpha) * p
        # Renormalize
        total = sum(blended.values())
        if total > 0:
            blended = {s: v / total for s, v in blended.items()}
        dist = blended
    else:
        dist = model_dist

    # Sort by probability descending
    ranked = sorted(dist.items(), key=lambda x: -x[1])

    best_score, best_prob = ranked[0]
    top_3 = [(f"{h}-{a}", round(p, 4)) for (h, a), p in ranked[:3]]

    # Expected goals from the distribution
    expected_goals = sum((h + a) * p for (h, a), p in dist.items())

    return {
        "score": best_score,
        "score_str": f"{best_score[0]}-{best_score[1]}",
        "prob": round(best_prob, 4),
        "expected_goals": round(expected_goals, 2),
        "top_3": top_3,
    }
