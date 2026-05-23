"""Ingest Reddit posts from a small set of WC-relevant subreddits.

For each post:
  - persist as SocialPost (idempotent on URL)
  - tag to a Team when that team's name appears in title or body text
"""

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.models import Competition, SocialPost, Team


log = get_logger(__name__)


WC_RELEVANT_SUBREDDITS = ["soccer", "worldcup", "footballtactics"]


async def ingest_reddit_for_competition(collector, max_posts: int = 50) -> dict[str, int]:
    """Fetch recent posts from WC-relevant subreddits and persist as SocialPost rows.

    Returns {"posts_inserted": int}.
    """
    settings = get_settings()
    inserted = 0

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one()
        teams = (await session.execute(select(Team))).scalars().all()
        team_by_name_lower = {t.name.lower(): t for t in teams}
        existing_urls = {
            row.url
            for row in (await session.execute(select(SocialPost))).scalars().all()
        }

        try:
            from connectors.reddit import RedditCollectSpec
        except ImportError:
            RedditCollectSpec = None

        spec = _build_spec(WC_RELEVANT_SUBREDDITS, max_posts, RedditCollectSpec)
        result = await collector.fetch(spec)
        if getattr(result, "status", "success") != "success":
            log.warning("ingest.reddit.failed")
            return {"posts_inserted": 0}

        for post in getattr(result, "posts", []):
            url = getattr(post, "url", None)
            if url is None or url in existing_urls:
                continue
            text = getattr(post, "text", None) or ""
            ts = getattr(post, "created_at", None)
            if ts is None:
                continue
            team_id = _detect_team(text, team_by_name_lower)
            session.add(SocialPost(
                competition_id=comp.id,
                match_id=None,
                team_id=team_id,
                platform="reddit",
                external_id=str(getattr(post, "id", "") or ""),
                ts=ts,
                author=getattr(post, "author", None),
                text=text,
                engagement=int(getattr(post, "score", 0) or 0),
                url=url,
            ))
            existing_urls.add(url)
            inserted += 1

        await session.commit()

    log.info("ingest.reddit", posts_inserted=inserted)
    return {"posts_inserted": inserted}


def _build_spec(subreddits, max_posts, spec_cls):
    """Build a RedditCollectSpec; falls back to a duck-typed object if the
    connectors module isn't installed (tests inject a fake collector).

    The actual spec requires subreddits list and other parameters. Tests provide
    a minimal spec with just a subreddits attribute.
    """
    if spec_cls is None:
        # Tests inject a fake collector whose .fetch() just ignores spec — duck-typing.
        class _Spec:
            pass
        s = _Spec()
        s.subreddits = subreddits
        s.max_posts_per_subreddit = max_posts
        return s
    # Production: use actual RedditCollectSpec with reasonable defaults
    return spec_cls(
        subreddits=subreddits,
        max_posts_per_subreddit=max_posts,
        sort="hot",
        time_filter="day",
        include_comments=False,
    )


def _detect_team(text: str, team_by_name_lower: dict[str, "Team"]) -> int | None:
    """Best-effort match: returns the team_id when one (and only one) team name is
    found in the text. If multiple teams match, returns None (ambiguous — let
    aggregator handle multi-team posts later)."""
    text_lower = text.lower()
    matched = []
    for name_lower, team in team_by_name_lower.items():
        if name_lower in text_lower:
            matched.append(team.id)
    if len(matched) == 1:
        return matched[0]
    return None
