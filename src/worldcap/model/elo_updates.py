"""Apply Elo updates to TeamRating rows from newly-completed matches.

Pure orchestration: pulls match scores from DB, computes new ratings via
elo.update_ratings, persists. Idempotent at the call level — the caller passes
only newly-completed match ids; this function does not re-process matches.
"""

from datetime import datetime, timezone

from sqlmodel import select

from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.model.elo import INITIAL_RATING, update_ratings
from worldcap.models import Match, TeamRating


log = get_logger(__name__)


def _result_from_score(home_score: int, away_score: int) -> float:
    if home_score > away_score:
        return 1.0
    if home_score < away_score:
        return 0.0
    return 0.5


async def apply_elo_updates(completed_match_ids: list[int]) -> dict:
    """Apply Elo updates for the given completed match ids.

    Returns {"updates_applied": int, "matches_missing_ratings": int}.
    Matches lacking ratings for either team get a default INITIAL_RATING.
    """
    if not completed_match_ids:
        return {"updates_applied": 0, "matches_missing_ratings": 0}

    updates_applied = 0
    missing_ratings = 0
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        matches = (await session.execute(
            select(Match).where(Match.id.in_(completed_match_ids))
        )).scalars().all()

        ratings_by_team = {
            r.team_id: r
            for r in (await session.execute(select(TeamRating))).scalars().all()
        }

        for m in matches:
            if (
                m.home_team_id is None or m.away_team_id is None
                or m.home_score is None or m.away_score is None
            ):
                continue
            home_rating_row = ratings_by_team.get(m.home_team_id)
            away_rating_row = ratings_by_team.get(m.away_team_id)

            if home_rating_row is None:
                home_rating_row = TeamRating(
                    team_id=m.home_team_id, rating=INITIAL_RATING,
                    last_updated=now, source="seed",
                )
                session.add(home_rating_row)
                ratings_by_team[m.home_team_id] = home_rating_row
                missing_ratings += 1
            if away_rating_row is None:
                away_rating_row = TeamRating(
                    team_id=m.away_team_id, rating=INITIAL_RATING,
                    last_updated=now, source="seed",
                )
                session.add(away_rating_row)
                ratings_by_team[m.away_team_id] = away_rating_row
                missing_ratings += 1

            await session.flush()

            new_home, new_away = update_ratings(
                home_rating_row.rating,
                away_rating_row.rating,
                result=_result_from_score(m.home_score, m.away_score),
                stage=m.stage,
            )
            home_rating_row.rating = new_home
            home_rating_row.last_updated = now
            home_rating_row.source = "in_tournament"
            away_rating_row.rating = new_away
            away_rating_row.last_updated = now
            away_rating_row.source = "in_tournament"
            updates_applied += 1

        await session.commit()

    log.info("elo.updates", updates_applied=updates_applied, missing_ratings=missing_ratings)
    return {"updates_applied": updates_applied, "matches_missing_ratings": missing_ratings}
