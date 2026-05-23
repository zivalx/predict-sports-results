from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.enrich.aggregate import aggregate_team_sentiment
from worldcap.models import NewsItem, SentimentScore, SocialPost, Team
from worldcap.models.tournament import Competition
from scripts.seed_competition import seed


async def _seed():
    await init_db()
    await seed()
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}

        # Brazil: 2 posts (+0.6, -0.2), 1 news (+0.4)  → mean = (0.6 + (-0.2) + 0.4)/3 ≈ 0.267
        # France: 1 post (-0.5), 1 news (-0.3)         → mean = -0.4
        # Old post for Brazil outside lookback window: 0.9 (must NOT be included)
        now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
        p1 = SocialPost(competition_id=comp.id, team_id=teams["Brazil"].id,
                        platform="reddit", ts=now - timedelta(hours=1),
                        text="bzr1", url="https://x.com/p1")
        p2 = SocialPost(competition_id=comp.id, team_id=teams["Brazil"].id,
                        platform="reddit", ts=now - timedelta(hours=2),
                        text="bzr2", url="https://x.com/p2")
        p3 = SocialPost(competition_id=comp.id, team_id=teams["France"].id,
                        platform="reddit", ts=now - timedelta(hours=3),
                        text="fra1", url="https://x.com/p3")
        p_old = SocialPost(competition_id=comp.id, team_id=teams["Brazil"].id,
                           platform="reddit", ts=now - timedelta(hours=200),
                           text="bzr-old", url="https://x.com/p_old")
        n1 = NewsItem(competition_id=comp.id, team_id=teams["Brazil"].id,
                      source="gnews", url="https://news/n1", ts=now - timedelta(hours=4),
                      title="bra news")
        n2 = NewsItem(competition_id=comp.id, team_id=teams["France"].id,
                      source="gnews", url="https://news/n2", ts=now - timedelta(hours=5),
                      title="fra news")
        for x in [p1, p2, p3, p_old, n1, n2]:
            session.add(x)
        await session.flush()

        # SentimentScores
        items = (await session.execute(select(SocialPost))).scalars().all()
        news = (await session.execute(select(NewsItem))).scalars().all()
        p_by_url = {p.url: p for p in items}
        n_by_url = {n.url: n for n in news}

        session.add_all([
            SentimentScore(target_type="post", target_id=p_by_url["https://x.com/p1"].id,
                           ts=now, score=0.6, confidence=1.0),
            SentimentScore(target_type="post", target_id=p_by_url["https://x.com/p2"].id,
                           ts=now, score=-0.2, confidence=1.0),
            SentimentScore(target_type="post", target_id=p_by_url["https://x.com/p3"].id,
                           ts=now, score=-0.5, confidence=1.0),
            SentimentScore(target_type="post", target_id=p_by_url["https://x.com/p_old"].id,
                           ts=now, score=0.9, confidence=1.0),
            SentimentScore(target_type="news_item", target_id=n_by_url["https://news/n1"].id,
                           ts=now, score=0.4, confidence=1.0),
            SentimentScore(target_type="news_item", target_id=n_by_url["https://news/n2"].id,
                           ts=now, score=-0.3, confidence=1.0),
        ])
        await session.commit()


@pytest.mark.asyncio
async def test_aggregate_team_sentiment_uses_recent_window():
    await _seed()
    as_of = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)

    summary = await aggregate_team_sentiment(as_of=as_of, lookback_hours=72)
    assert summary["teams_aggregated"] == 2

    async with get_session() as session:
        team_scores = (await session.execute(
            select(SentimentScore).where(SentimentScore.target_type == "team")
        )).scalars().all()
        teams = {t.id: t for t in (await session.execute(select(Team))).scalars().all()}
    assert len(team_scores) == 2

    by_team = {teams[s.target_id].name: s for s in team_scores}
    # Brazil: 3 recent items, score average ≈ (0.6 - 0.2 + 0.4) / 3 = 0.267 (old 0.9 excluded)
    assert abs(by_team["Brazil"].score - 0.2666666666) < 1e-3
    # France: 2 items: (-0.5 - 0.3) / 2 = -0.4
    assert abs(by_team["France"].score - (-0.4)) < 1e-3


@pytest.mark.asyncio
async def test_aggregate_idempotent_replaces_previous_aggregate():
    await _seed()
    as_of = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)

    await aggregate_team_sentiment(as_of=as_of, lookback_hours=72)
    await aggregate_team_sentiment(as_of=as_of, lookback_hours=72)  # re-run

    async with get_session() as session:
        team_scores = (await session.execute(
            select(SentimentScore).where(SentimentScore.target_type == "team")
        )).scalars().all()
    # Still 2 (one per team) — second run replaced rather than appended.
    assert len(team_scores) == 2


@pytest.mark.asyncio
async def test_aggregate_returns_zero_when_no_underlying_scores():
    await init_db()
    await seed()
    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.commit()

    summary = await aggregate_team_sentiment(
        as_of=datetime(2026, 5, 23, tzinfo=timezone.utc),
        lookback_hours=72,
    )
    assert summary == {"teams_aggregated": 0}
