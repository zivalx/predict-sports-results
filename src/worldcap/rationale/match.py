"""Generate a 2-3 sentence rationale paragraph for a given MatchForecast row.

Loads the related context (Match, Teams, ratings, recent news, team-sentiment),
builds a structured prompt, calls Claude (smart model), and persists the
resulting text on MatchForecast.rationale_md.
"""

from datetime import datetime, timedelta

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.models import (
    MatchForecast,
    NewsItem,
    SentimentScore,
    Team,
    TeamRating,
)
from worldcap.models.tournament import Match
from worldcap.rationale.prompts import MatchPromptContext, build_match_rationale_prompt


log = get_logger(__name__)


async def generate_rationale_for_match(
    claude_client,
    match_forecast_id: int,
    news_lookback_hours: int = 72,
    max_tokens: int = 220,
) -> dict:
    """Generate + persist a rationale for one MatchForecast. Returns
    {"rationale_written": bool}.
    """
    if claude_client.is_disabled():
        log.warning("rationale.client_disabled")
        return {"rationale_written": False}

    settings = get_settings()
    model = settings.rationale_model

    async with get_session() as session:
        mf = (await session.execute(
            select(MatchForecast).where(MatchForecast.id == match_forecast_id)
        )).scalar_one_or_none()
        if mf is None:
            log.warning("rationale.match_forecast_not_found", id=match_forecast_id)
            return {"rationale_written": False}

        match = (await session.execute(
            select(Match).where(Match.id == mf.match_id)
        )).scalar_one()
        teams = (await session.execute(select(Team))).scalars().all()
        team_by_id = {t.id: t for t in teams}
        home = team_by_id.get(match.home_team_id)
        away = team_by_id.get(match.away_team_id)
        if home is None or away is None:
            log.warning("rationale.teams_missing", match_id=match.id)
            return {"rationale_written": False}

        ratings_by_team = {
            r.team_id: r.rating
            for r in (await session.execute(select(TeamRating))).scalars().all()
        }

        # Recent headlines per team
        window_start = (match.kickoff_utc or datetime.utcnow()) - timedelta(hours=news_lookback_hours)
        home_news = (await session.execute(
            select(NewsItem)
            .where(NewsItem.team_id == home.id)
            .where(NewsItem.ts >= window_start)
            .order_by(NewsItem.ts.desc())
            .limit(3)
        )).scalars().all()
        away_news = (await session.execute(
            select(NewsItem)
            .where(NewsItem.team_id == away.id)
            .where(NewsItem.ts >= window_start)
            .order_by(NewsItem.ts.desc())
            .limit(3)
        )).scalars().all()

        team_sentiments = {
            s.target_id: s.score
            for s in (await session.execute(
                select(SentimentScore).where(SentimentScore.target_type == "team")
            )).scalars().all()
        }

        ctx = MatchPromptContext(
            home_name=home.name,
            away_name=away.name,
            stage=match.stage,
            group_label=match.group_label,
            kickoff_iso=match.kickoff_utc.strftime("%Y-%m-%dT%H:%M UTC"),
            home_rating=ratings_by_team.get(home.id, 1500.0),
            away_rating=ratings_by_team.get(away.id, 1500.0),
            our_p_home=mf.p_home,
            our_p_draw=mf.p_draw,
            our_p_away=mf.p_away,
            poly_p_home=mf.p_home_poly,
            poly_p_draw=mf.p_draw_poly,
            poly_p_away=mf.p_away_poly,
            edge_vs_poly=mf.edge_vs_poly,
            home_recent_news=[n.title for n in home_news],
            away_recent_news=[n.title for n in away_news],
            home_sentiment=team_sentiments.get(home.id),
            away_sentiment=team_sentiments.get(away.id),
        )

    prompt = build_match_rationale_prompt(ctx)

    # Call outside the session (no DB writes during the LLM call)
    try:
        result = await claude_client.complete(prompt=prompt, model=model, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "rationale.call_failed",
            match_forecast_id=match_forecast_id,
            error=str(exc),
        )
        return {"rationale_written": False, "error": str(exc)}
    if result is None:
        return {"rationale_written": False}

    text = (result.text or "").strip()
    if not text:
        return {"rationale_written": False}

    async with get_session() as session:
        # Re-fetch to update
        mf = (await session.execute(
            select(MatchForecast).where(MatchForecast.id == match_forecast_id)
        )).scalar_one()
        mf.rationale_md = text
        await session.commit()

    log.info(
        "rationale.match",
        match_forecast_id=match_forecast_id,
        chars=len(text),
        tokens_used=result.output_tokens,
    )
    return {"rationale_written": True}
