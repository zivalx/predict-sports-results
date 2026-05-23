"""Ingest completed-match results from the sports-data API.

A match is "newly completed" if its DB status was NOT FT before this run and
the API now reports FT with a final score. Returns the list of those match IDs
so callers can trigger downstream side-effects (Elo updates, etc).
"""

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.ingest.sports_data import FootballDataClient
from worldcap.log import get_logger
from worldcap.models import Match, Team
from worldcap.models.tournament import Competition

log = get_logger(__name__)


async def ingest_completed_results(client: FootballDataClient) -> dict:
    """Return {'newly_completed': int, 'match_ids': list[int]}."""
    settings = get_settings()
    teams_dto = await client.get_teams(settings.competition_code)
    fixtures_dto = await client.get_fixtures(settings.competition_code)

    newly_completed_ids: list[int] = []

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one()

        # Upsert teams (lightweight — most cases the rows already exist from T8)
        existing_team_ext = {
            t.external_id: t
            for t in (await session.execute(select(Team))).scalars().all()
        }
        for dto in teams_dto:
            if dto.external_id not in existing_team_ext:
                session.add(Team(
                    external_id=dto.external_id,
                    name=dto.name,
                    country_code=dto.country_code,
                ))
        await session.flush()

        ext_to_id = {
            t.external_id: t.id
            for t in (await session.execute(select(Team))).scalars().all()
        }

        existing_matches = {
            m.external_id: m
            for m in (await session.execute(select(Match))).scalars().all()
        }

        for dto in fixtures_dto:
            home_id = ext_to_id.get(dto.home_external_id) if dto.home_external_id else None
            away_id = ext_to_id.get(dto.away_external_id) if dto.away_external_id else None
            row = existing_matches.get(dto.external_id)
            if row is None:
                # New match — insert with current state. Count as newly-completed if FT.
                match = Match(
                    external_id=dto.external_id,
                    competition_id=comp.id,
                    stage=dto.stage,
                    group_label=dto.group_label,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    kickoff_utc=dto.kickoff_utc,
                    status=dto.status,
                    home_score=dto.home_score,
                    away_score=dto.away_score,
                )
                session.add(match)
                if dto.status == "FT":
                    # Flush to get the ID, then record as newly completed
                    await session.flush()
                    newly_completed_ids.append(match.id)
                continue

            was_ft = row.status == "FT"
            is_ft = dto.status == "FT"
            row.status = dto.status
            row.home_score = dto.home_score
            row.away_score = dto.away_score
            row.home_team_id = home_id
            row.away_team_id = away_id
            row.kickoff_utc = dto.kickoff_utc
            if is_ft and not was_ft:
                newly_completed_ids.append(row.id)

        await session.commit()

    log.info("ingest.results", newly_completed=len(newly_completed_ids))
    return {"newly_completed": len(newly_completed_ids), "match_ids": newly_completed_ids}
