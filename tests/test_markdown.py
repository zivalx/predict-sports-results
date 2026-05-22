from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.model.naive import generate_naive_forecast
from worldcap.models import OddsSnapshot, Team
from worldcap.models.tournament import Competition, Match
from worldcap.render.markdown import render_digest_markdown
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_renders_pretournament_digest_with_outlook_and_next_fixtures():
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
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "France": 0.18},
        ))
        session.add(Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")
    text = await render_digest_markdown(
        snapshot_id=snap.id,
        as_of=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert "World Cup" in text
    assert "T−" in text
    assert "Tournament outlook" in text
    assert "Brazil" in text
    assert "25" in text
    assert "Next matches" in text
    assert "Brazil vs France" in text
