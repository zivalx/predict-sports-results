from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.ingest.sports_data import FootballDataClient
from worldcap.models import Competition, Match, Team


async def ingest_teams_and_fixtures(client: FootballDataClient) -> dict[str, int]:
    settings = get_settings()
    teams_dto = await client.get_teams(settings.competition_code)
    fixtures_dto = await client.get_fixtures(settings.competition_code)

    teams_upserted = 0
    matches_upserted = 0

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == get_settings().db_competition_code)
        )).scalar_one()

        # Upsert teams
        existing_by_ext = {
            t.external_id: t
            for t in (await session.execute(select(Team))).scalars().all()
        }
        for dto in teams_dto:
            if dto.external_id in existing_by_ext:
                row = existing_by_ext[dto.external_id]
                changed = False
                if row.name != dto.name:
                    row.name = dto.name
                    changed = True
                if row.country_code != dto.country_code:
                    row.country_code = dto.country_code
                    changed = True
                if changed:
                    teams_upserted += 1
            else:
                session.add(Team(
                    external_id=dto.external_id,
                    name=dto.name,
                    country_code=dto.country_code,
                ))
                teams_upserted += 1
        await session.flush()

        # Refresh team map
        ext_to_id = {
            t.external_id: t.id
            for t in (await session.execute(select(Team))).scalars().all()
        }

        # Upsert matches
        existing_matches = {
            m.external_id: m
            for m in (await session.execute(select(Match))).scalars().all()
        }
        for dto in fixtures_dto:
            home_id = ext_to_id.get(dto.home_external_id) if dto.home_external_id else None
            away_id = ext_to_id.get(dto.away_external_id) if dto.away_external_id else None
            if dto.external_id in existing_matches:
                row = existing_matches[dto.external_id]
                row.home_team_id = home_id
                row.away_team_id = away_id
                row.kickoff_utc = dto.kickoff_utc
                row.status = dto.status
                row.home_score = dto.home_score
                row.away_score = dto.away_score
                matches_upserted += 1
            else:
                session.add(Match(
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
                ))
                matches_upserted += 1

        await session.commit()

    return {"teams_upserted": teams_upserted, "matches_upserted": matches_upserted}
