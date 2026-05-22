from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.model.naive import generate_naive_forecast
from worldcap.model.per_match import generate_match_forecasts
from worldcap.models import OddsSnapshot, Team, TeamRating
from worldcap.models.tournament import Competition, Match
from worldcap.render.markdown import render_digest_markdown
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_renders_pretournament_digest_with_outlook_and_per_match():
    await init_db()
    await seed()

    as_of = datetime(2026, 6, 5, tzinfo=timezone.utc)

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add_all([
            TeamRating(team_id=teams["Brazil"].id, rating=1790.0, last_updated=as_of, source="seed"),
            TeamRating(team_id=teams["France"].id, rating=1830.0, last_updated=as_of, source="seed"),
        ])
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=as_of,
            outcomes={"Brazil": 0.25, "France": 0.18},
        ))
        session.add(Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=as_of + timedelta(days=6),
            status="SCHEDULED",
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")
    await generate_match_forecasts(snapshot_id=snap.id, as_of=as_of)
    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)

    assert "World Cup" in text
    assert "T−" in text  # pre-tournament countdown
    assert "Tournament outlook" in text
    assert "Per-match forecasts" in text
    assert "Brazil vs France" in text
    assert "Our forecast" in text
    assert "Polymarket:** —" in text  # no per-match Polymarket in Plan 2
    assert "Next matches" in text
