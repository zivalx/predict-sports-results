from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.ingest.news import ingest_news_for_teams
from worldcup.models import NewsItem, Team
from worldcup.models.tournament import Competition
from scripts.seed_competition import seed


def _fake_article(url, title, summary, ts):
    """Minimal fake of a GNews article result."""
    a = MagicMock()
    a.url = url
    a.title = title
    a.description = summary
    a.published_at = ts
    return a


@pytest.fixture
def fake_gnews_collector():
    """Returns canned articles per team query."""
    collector = MagicMock()

    async def fetch(spec):
        # spec.query contains the team name; return 2 articles for any query
        q = spec.query
        return MagicMock(status="success", articles=[
            _fake_article(
                url=f"https://example.com/{q.replace(' ', '-')}-1",
                title=f"{q} news 1",
                summary=f"Story about {q}",
                ts=datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc),
            ),
            _fake_article(
                url=f"https://example.com/{q.replace(' ', '-')}-2",
                title=f"{q} news 2",
                summary=f"Another story about {q}",
                ts=datetime(2026, 5, 23, 11, 0, tzinfo=timezone.utc),
            ),
        ])

    collector.fetch = AsyncMock(side_effect=fetch)
    return collector


@pytest.mark.asyncio
async def test_ingest_news_persists_articles(fake_gnews_collector):
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.commit()

    summary = await ingest_news_for_teams(fake_gnews_collector)
    # 2 teams × 2 articles each = 4 inserts
    assert summary["items_inserted"] == 4

    async with get_session() as session:
        items = (await session.execute(select(NewsItem))).scalars().all()
    assert len(items) == 4
    titles = {i.title for i in items}
    assert "Brazil news 1" in titles
    assert "France news 2" in titles


@pytest.mark.asyncio
async def test_ingest_news_is_idempotent(fake_gnews_collector):
    await init_db()
    await seed()
    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.commit()

    await ingest_news_for_teams(fake_gnews_collector)
    second = await ingest_news_for_teams(fake_gnews_collector)
    assert second["items_inserted"] == 0  # URLs already present

    async with get_session() as session:
        items = (await session.execute(select(NewsItem))).scalars().all()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_ingest_news_no_teams_returns_zero(fake_gnews_collector):
    await init_db()
    await seed()
    # No teams seeded.
    summary = await ingest_news_for_teams(fake_gnews_collector)
    assert summary == {"items_inserted": 0}
