"""Apply Elo updates from completed matches.

Self-contained: queries for FT matches where elo_applied=False, processes
them in kickoff order, marks each as applied. No dependency on other
pipeline steps passing match IDs — idempotent and self-healing.
"""

from datetime import datetime, timezone

from sqlmodel import select

from worldcup.db import get_session
from worldcup.log import get_logger
from worldcup.model.elo import INITIAL_RATING, update_ratings
from worldcup.models import Match, TeamRating


log = get_logger(__name__)


def _result_from_score(home_score: int, away_score: int) -> float:
    if home_score > away_score:
        return 1.0
    if home_score < away_score:
        return 0.0
    return 0.5


async def apply_elo_updates(completed_match_ids: list[int] | None = None) -> dict:
    """Apply Elo updates for all completed matches not yet processed.

    Finds FT matches with scores where elo_applied=False, processes them
    in kickoff order, and marks each as applied.

    The completed_match_ids parameter is accepted for backward compatibility
    but ignored — the function discovers unprocessed matches on its own.

    Returns {"updates_applied": int, "matches_missing_ratings": int}.
    """
    updates_applied = 0
    missing_ratings = 0
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        # Find all FT matches with scores that haven't had Elo applied
        matches = (await session.execute(
            select(Match)
            .where(Match.status == "FT")
            .where(Match.home_score.is_not(None))
            .where(Match.away_score.is_not(None))
            .where(Match.elo_applied == False)  # noqa: E712
            .where(Match.home_team_id.is_not(None))
            .where(Match.away_team_id.is_not(None))
            .order_by(Match.kickoff_utc.asc())
        )).scalars().all()

        if not matches:
            return {"updates_applied": 0, "matches_missing_ratings": 0}

        ratings_by_team = {
            r.team_id: r
            for r in (await session.execute(select(TeamRating))).scalars().all()
        }

        for m in matches:
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

            m.elo_applied = True
            updates_applied += 1

        await session.commit()

    log.info("elo.updates", updates_applied=updates_applied, missing_ratings=missing_ratings)
    return {"updates_applied": updates_applied, "matches_missing_ratings": missing_ratings}
