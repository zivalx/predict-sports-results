"""Ingest team-relevant news from GNews into NewsItem rows.

For each Team, query GNews with the team name and persist new articles as
NewsItem rows. Idempotent by URL (NewsItem.url is unique).
"""

from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.log import get_logger
from worldcup.models import Competition, NewsItem, Team


log = get_logger(__name__)


async def ingest_news_for_teams(collector, lookback_hours: int = 72) -> dict[str, int]:
    """Pulls news per Team and writes NewsItem rows. Idempotent on URL.

    Returns {"items_inserted": int}.
    """
    settings = get_settings()
    inserted = 0

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one()
        teams = (await session.execute(select(Team))).scalars().all()
        if not teams:
            return {"items_inserted": 0}

        existing_urls = {
            row.url
            for row in (await session.execute(select(NewsItem))).scalars().all()
        }

        # IMPORT REAL SPEC — from connectors.gnews module
        try:
            from connectors.gnews import GNewsCollectSpec  # noqa: WPS433
        except ImportError:
            GNewsCollectSpec = None

        for team in teams:
            spec = _build_spec(team.name, lookback_hours, GNewsCollectSpec)
            result = await collector.fetch(spec)
            if not getattr(result, "status", "success") == "success":
                log.warning("ingest.news.failed", team=team.name)
                continue
            for article in getattr(result, "articles", []):
                url = getattr(article, "url", None)
                if url is None or url in existing_urls:
                    continue
                title = getattr(article, "title", "") or ""
                summary = getattr(article, "description", None) or getattr(article, "summary", None)
                ts = getattr(article, "published_at", None) or getattr(article, "published_date", None)
                if ts is None:
                    continue
                session.add(NewsItem(
                    competition_id=comp.id,
                    match_id=None,
                    team_id=team.id,
                    source="gnews",
                    url=url,
                    ts=ts,
                    title=title,
                    summary=summary,
                    raw={},
                ))
                existing_urls.add(url)
                inserted += 1

        await session.commit()

    log.info("ingest.news", items_inserted=inserted)
    return {"items_inserted": inserted}


def _build_spec(query: str, lookback_hours: int, spec_cls):
    """Build a GNewsCollectSpec; falls back to a MagicMock-shaped object if the
    connectors module isn't installed (tests inject a fake collector).

    Mediates between the actual GNewsCollectSpec interface and duck-typed specs
    used in tests. The actual spec requires query and optional parameters like
    from_date, to_date, max_results, etc. Tests provide a minimal spec with just
    a query attribute.
    """
    if spec_cls is None:
        # Tests inject a fake collector whose .fetch() just reads spec.query — duck-typing.
        class _Spec:
            pass
        s = _Spec()
        s.query = query
        s.lookback_hours = lookback_hours
        return s
    # Production: use actual GNewsCollectSpec with reasonable defaults for team queries
    return spec_cls(
        query=query,
        language="en",
        sort_by="publishedAt",
        max_results=10,
    )
