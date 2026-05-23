from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.enrich.claude_client import FakeClaudeClient
from worldcap.enrich.sentiment import score_unscored_items
from worldcap.models import NewsItem, SentimentScore, SocialPost, Team
from worldcap.models.tournament import Competition
from scripts.seed_competition import seed


async def _seed_content(n_posts: int = 3, n_news: int = 2):
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.flush()
        team = (await session.execute(select(Team))).scalar_one()
        for i in range(n_posts):
            session.add(SocialPost(
                competition_id=comp.id,
                team_id=team.id,
                platform="reddit",
                external_id=f"p{i}",
                ts=datetime(2026, 5, 23, 10, i, tzinfo=timezone.utc),
                text=f"Some post text {i}",
                url=f"https://reddit.com/p{i}",
            ))
        for j in range(n_news):
            session.add(NewsItem(
                competition_id=comp.id,
                team_id=team.id,
                source="gnews",
                url=f"https://news.example/{j}",
                ts=datetime(2026, 5, 23, 12, j, tzinfo=timezone.utc),
                title=f"News {j}",
                summary=f"Some news summary {j}",
            ))
        await session.commit()


@pytest.mark.asyncio
async def test_score_unscored_writes_one_score_per_post_and_news_item():
    await init_db()
    await seed()
    await _seed_content(n_posts=3, n_news=2)

    client = FakeClaudeClient(canned_score=0.5)
    summary = await score_unscored_items(client, limit=100)

    assert summary["posts_scored"] == 3
    assert summary["items_scored"] == 2
    assert summary["tokens_used"] > 0
    assert client.calls == 5  # one per item

    async with get_session() as session:
        scores = (await session.execute(select(SentimentScore))).scalars().all()
    assert len(scores) == 5
    post_scores = [s for s in scores if s.target_type == "post"]
    news_scores = [s for s in scores if s.target_type == "news_item"]
    assert len(post_scores) == 3
    assert len(news_scores) == 2
    for s in scores:
        assert s.score == 0.5
        assert s.confidence == 1.0


@pytest.mark.asyncio
async def test_score_unscored_is_idempotent():
    await init_db()
    await seed()
    await _seed_content(n_posts=2, n_news=1)

    client = FakeClaudeClient(canned_score=0.3)
    await score_unscored_items(client, limit=100)
    second = await score_unscored_items(client, limit=100)

    # Second call should find nothing unscored
    assert second == {"posts_scored": 0, "items_scored": 0, "tokens_used": 0}

    async with get_session() as session:
        scores = (await session.execute(select(SentimentScore))).scalars().all()
    assert len(scores) == 3


@pytest.mark.asyncio
async def test_score_respects_limit_param():
    await init_db()
    await seed()
    await _seed_content(n_posts=5, n_news=5)

    client = FakeClaudeClient(canned_score=0.0)
    summary = await score_unscored_items(client, limit=3)
    # limit caps the total work across posts+news; exact split is implementation-defined.
    # Just assert the total scored ≤ 3.
    assert summary["posts_scored"] + summary["items_scored"] <= 3


@pytest.mark.asyncio
async def test_disabled_client_short_circuits():
    await init_db()
    await seed()
    await _seed_content(n_posts=2, n_news=2)

    client = FakeClaudeClient(canned_score=0.0, disabled=True)
    summary = await score_unscored_items(client, limit=100)
    assert summary == {"posts_scored": 0, "items_scored": 0, "tokens_used": 0}

    async with get_session() as session:
        scores = (await session.execute(select(SentimentScore))).scalars().all()
    assert len(scores) == 0
