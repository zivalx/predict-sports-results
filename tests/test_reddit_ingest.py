from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.ingest.reddit import ingest_reddit_for_competition
from worldcap.models import SocialPost, Team
from worldcap.models.tournament import Competition
from scripts.seed_competition import seed


def _post(post_id: str, title: str, body: str = "", subreddit: str = "soccer"):
    p = MagicMock()
    p.id = post_id
    p.title = title
    p.text = title + " " + body
    p.author = "anon"
    p.score = 100
    p.subreddit = subreddit
    p.url = f"https://reddit.com/r/{subreddit}/comments/{post_id}/"
    p.created_at = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    return p


@pytest.fixture
def fake_reddit_collector():
    """Returns canned posts; ignores subreddit and just returns a fixed list."""
    collector = MagicMock()

    async def fetch(spec):
        return MagicMock(status="success", posts=[
            _post("a1", "Brazil look strong in friendlies", "Vinicius scored twice"),
            _post("a2", "France team selection drama", "Mbappe quotes from presser"),
            _post("a3", "Random WC analytics post", "Long-form take on Group G"),
            _post("a4", "Tite addresses Brazil squad", "Coach defends rotation"),
        ])

    collector.fetch = AsyncMock(side_effect=fetch)
    return collector


@pytest.mark.asyncio
async def test_ingest_reddit_persists_and_tags_teams(fake_reddit_collector):
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.commit()

    summary = await ingest_reddit_for_competition(fake_reddit_collector)
    assert summary["posts_inserted"] == 4

    async with get_session() as session:
        teams_by_name = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        posts = (await session.execute(select(SocialPost))).scalars().all()
    assert len(posts) == 4

    # Team-tagging by name appearance in text
    brazil1 = next(p for p in posts if "Brazil look strong" in p.text)
    france1 = next(p for p in posts if "France team selection" in p.text)
    untagged = next(p for p in posts if "Random WC analytics" in p.text)
    assert brazil1.team_id == teams_by_name["Brazil"].id
    assert france1.team_id == teams_by_name["France"].id
    assert untagged.team_id is None


@pytest.mark.asyncio
async def test_ingest_reddit_idempotent(fake_reddit_collector):
    await init_db()
    await seed()
    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.commit()

    await ingest_reddit_for_competition(fake_reddit_collector)
    second = await ingest_reddit_for_competition(fake_reddit_collector)
    assert second["posts_inserted"] == 0

    async with get_session() as session:
        posts = (await session.execute(select(SocialPost))).scalars().all()
    assert len(posts) == 4
