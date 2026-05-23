"""Score unscored posts/news items via the Claude client → SentimentScore rows.

A 'post' or 'news_item' is considered unscored if there's no SentimentScore row
with matching (target_type, target_id). We score in arrival order (oldest first
by ts) capped at `limit` total items per call to keep refresh latency bounded.
"""

from datetime import datetime, timezone

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.enrich.claude_client import _BaseClaudeClient
from worldcap.log import get_logger
from worldcap.models import NewsItem, SentimentScore, SocialPost


log = get_logger(__name__)


async def score_unscored_items(client, limit: int = 50) -> dict[str, int]:
    """Score up to `limit` unscored SocialPost + NewsItem rows.

    Returns {"posts_scored": int, "items_scored": int, "tokens_used": int}.
    """
    if client.is_disabled():
        log.warning("sentiment.client_disabled_skipped")
        return {"posts_scored": 0, "items_scored": 0, "tokens_used": 0}

    settings = get_settings()
    model = settings.sentiment_model

    posts_scored = 0
    items_scored = 0
    tokens_before = client.tokens_used

    async with get_session() as session:
        # Get scored IDs to filter unscored items
        scored = (await session.execute(select(SentimentScore))).scalars().all()
        scored_post_ids = {s.target_id for s in scored if s.target_type == "post"}
        scored_news_ids = {s.target_id for s in scored if s.target_type == "news_item"}

        # Pull unscored posts, oldest first
        unscored_posts = (await session.execute(
            select(SocialPost)
            .where(SocialPost.id.notin_(scored_post_ids) if scored_post_ids else SocialPost.id == SocialPost.id)
            .order_by(SocialPost.ts.asc())
        )).scalars().all()
        unscored_news = (await session.execute(
            select(NewsItem)
            .where(NewsItem.id.notin_(scored_news_ids) if scored_news_ids else NewsItem.id == NewsItem.id)
            .order_by(NewsItem.ts.asc())
        )).scalars().all()

        # Combine into one work queue, capped at limit
        work = []
        for p in unscored_posts:
            work.append(("post", p.id, p.text))
        for n in unscored_news:
            text = (n.title or "") + ("\n" + n.summary if n.summary else "")
            work.append(("news_item", n.id, text))
        work = work[:limit]

        now = datetime.now(timezone.utc)
        for target_type, target_id, text in work:
            result = await client.score_text(text, model=model)
            if result is None:
                continue
            session.add(SentimentScore(
                target_type=target_type,
                target_id=target_id,
                ts=now,
                score=result.score,
                confidence=result.confidence,
                model_version=model,
            ))
            if target_type == "post":
                posts_scored += 1
            else:
                items_scored += 1

        await session.commit()

    tokens_used = client.tokens_used - tokens_before
    log.info(
        "sentiment.scored",
        posts_scored=posts_scored,
        items_scored=items_scored,
        tokens_used=tokens_used,
    )
    return {
        "posts_scored": posts_scored,
        "items_scored": items_scored,
        "tokens_used": tokens_used,
    }
