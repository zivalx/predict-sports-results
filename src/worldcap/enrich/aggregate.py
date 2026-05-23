"""Aggregate per-post/per-news SentimentScores into per-team rollups.

For each team that has at least one item-level score within the lookback window,
compute a confidence-weighted mean of (post + news) scores and upsert a
SentimentScore row with target_type='team'.

Idempotency: when re-running for the same `as_of`/`lookback_hours`, the
team-level row is REPLACED, not appended, so the table stays at one rollup per
team.
"""

from datetime import datetime, timedelta

from sqlmodel import delete, select

from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.models import NewsItem, SentimentScore, SocialPost


log = get_logger(__name__)


MODEL_VERSION = "team-rollup-v0"


async def aggregate_team_sentiment(as_of: datetime, lookback_hours: int = 72) -> dict[str, int]:
    """Compute per-team confidence-weighted mean of item scores within the window.

    Returns {"teams_aggregated": int}.
    """
    window_start = as_of - timedelta(hours=lookback_hours)
    teams_aggregated = 0

    async with get_session() as session:
        # Fetch posts + news within the time window
        recent_posts = (await session.execute(
            select(SocialPost).where(SocialPost.ts >= window_start)
        )).scalars().all()
        recent_news = (await session.execute(
            select(NewsItem).where(NewsItem.ts >= window_start)
        )).scalars().all()

        if not recent_posts and not recent_news:
            log.info("aggregate.team_sentiment.no_recent")
            return {"teams_aggregated": 0}

        # Pull scores for those items
        scores = (await session.execute(select(SentimentScore))).scalars().all()
        post_scores = {s.target_id: s for s in scores if s.target_type == "post"}
        news_scores = {s.target_id: s for s in scores if s.target_type == "news_item"}

        # Accumulate per-team (weighted) sums
        per_team_score_sum: dict[int, float] = {}
        per_team_weight: dict[int, float] = {}

        for p in recent_posts:
            if p.team_id is None:
                continue
            s = post_scores.get(p.id)
            if s is None:
                continue
            w = s.confidence
            per_team_score_sum[p.team_id] = per_team_score_sum.get(p.team_id, 0.0) + s.score * w
            per_team_weight[p.team_id] = per_team_weight.get(p.team_id, 0.0) + w

        for n in recent_news:
            if n.team_id is None:
                continue
            s = news_scores.get(n.id)
            if s is None:
                continue
            w = s.confidence
            per_team_score_sum[n.team_id] = per_team_score_sum.get(n.team_id, 0.0) + s.score * w
            per_team_weight[n.team_id] = per_team_weight.get(n.team_id, 0.0) + w

        # Replace previous team rollups
        await session.execute(delete(SentimentScore).where(SentimentScore.target_type == "team"))

        for team_id, weight in per_team_weight.items():
            if weight <= 0:
                continue
            avg = per_team_score_sum[team_id] / weight
            session.add(SentimentScore(
                target_type="team",
                target_id=team_id,
                ts=as_of,
                score=avg,
                confidence=min(1.0, weight / 5.0),  # cap at 1.0; more items → more confidence
                model_version=MODEL_VERSION,
            ))
            teams_aggregated += 1

        await session.commit()

    log.info("aggregate.team_sentiment", teams_aggregated=teams_aggregated)
    return {"teams_aggregated": teams_aggregated}
