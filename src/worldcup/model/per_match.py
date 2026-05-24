"""Per-match forecast generator.

For every fixture-known scheduled match with kickoff in the future, compute
Elo-derived 3-way probabilities, optionally blend with a per-match Polymarket
market, and persist MatchForecast rows linked to the given snapshot.

Rationale generation (expensive Claude calls) is a separate step handled by
jobs/refresh.py with its own configurable horizon (RATIONALE_HORIZON_DAYS).

Plan 2 has no per-match Polymarket ingest yet, so market_p is always None.
Plan 3+ will plumb it through.
"""

from datetime import datetime

from sqlmodel import select

from worldcup.db import get_session
from worldcup.log import get_logger
from worldcup.model.match import blend_with_market, match_probabilities
from worldcup.models import ForecastSnapshot, Match, MatchForecast, TeamRating


log = get_logger(__name__)


async def generate_match_forecasts(
    snapshot_id: int,
    as_of: datetime,
) -> dict:
    """Write MatchForecast rows for ALL fixture-known scheduled matches with
    kickoff in the future. Generates probability forecasts; rationale generation
    is a separate step (handled by jobs/refresh.py with its own horizon).

    Returns {"forecasts_written": int, "matches_skipped_unrated": int}.
    Matches with no teams resolved (knockout slot placeholders) are silently
    skipped and not counted as "unrated".
    """
    forecasts_written = 0
    skipped_unrated = 0

    async with get_session() as session:
        snap = (await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.id == snapshot_id)
        )).scalar_one()

        matches = (await session.execute(
            select(Match)
            .where(Match.competition_id == snap.competition_id)
            .where(Match.kickoff_utc >= as_of)
            .where(Match.status == "SCHEDULED")
            .where(Match.home_team_id.is_not(None))
            .where(Match.away_team_id.is_not(None))
        )).scalars().all()

        ratings_by_team = {
            r.team_id: r.rating
            for r in (await session.execute(select(TeamRating))).scalars().all()
        }

        for m in matches:
            home_r = ratings_by_team.get(m.home_team_id)
            away_r = ratings_by_team.get(m.away_team_id)
            if home_r is None or away_r is None:
                skipped_unrated += 1
                continue

            model_p = match_probabilities(home_r, away_r)
            market_p = None  # Plan 3 will populate this from per-match Polymarket markets
            blended = blend_with_market(model_p, market_p)

            session.add(MatchForecast(
                snapshot_id=snapshot_id,
                match_id=m.id,
                p_home=blended["home"],
                p_draw=blended["draw"],
                p_away=blended["away"],
                p_home_poly=market_p["home"] if market_p else None,
                p_draw_poly=market_p["draw"] if market_p else None,
                p_away_poly=market_p["away"] if market_p else None,
                edge_vs_poly=0.0 if market_p is None else blended["home"] - market_p["home"],
                model_version="elo-v0",
            ))
            forecasts_written += 1

        await session.commit()

    log.info(
        "forecast.per_match",
        snapshot_id=snapshot_id,
        forecasts_written=forecasts_written,
        skipped_unrated=skipped_unrated,
    )
    return {
        "forecasts_written": forecasts_written,
        "matches_skipped_unrated": skipped_unrated,
    }
