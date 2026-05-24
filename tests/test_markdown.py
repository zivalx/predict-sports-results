from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.model.naive import generate_naive_forecast
from worldcup.model.per_match import generate_match_forecasts
from worldcup.models import OddsSnapshot, Team, TeamRating, Player, TopScorerForecast
from worldcup.models.tournament import Competition, Match
from worldcup.render.markdown import render_digest_markdown
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
    assert "Golden Boot race" in text
    assert "No watchlist players seeded yet" in text  # Empty state
    assert "Per-match forecasts" in text
    assert "Brazil vs France" in text
    assert "Our forecast" in text
    assert "Polymarket:** —" in text  # no per-match Polymarket in Plan 2
    assert "Next matches" in text


@pytest.mark.asyncio
async def test_renders_golden_boot_section_with_players():
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

    # Manually craft TopScorerForecast rows and Player entries
    async with get_session() as session:
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add_all([
            Player(name="Vinicius", team_id=teams["Brazil"].id, goals_per_90=0.7),
            Player(name="Mbappe", team_id=teams["France"].id, goals_per_90=0.9),
        ])
        await session.flush()
        players = {p.name: p for p in (await session.execute(select(Player))).scalars().all()}
        session.add_all([
            TopScorerForecast(
                snapshot_id=snap.id, player_id=players["Mbappe"].id,
                p_golden_boot=0.18, expected_goals=4.2,
                poly_p_top_scorer=0.16, edge_vs_poly=0.02,
            ),
            TopScorerForecast(
                snapshot_id=snap.id, player_id=players["Vinicius"].id,
                p_golden_boot=0.14, expected_goals=3.1,
                poly_p_top_scorer=None, edge_vs_poly=0.0,
            ),
        ])
        await session.commit()

    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
    assert "Golden Boot race" in text
    assert "Mbappe" in text
    assert "Vinicius" in text
    assert "P(top scorer)" in text
    assert "18.0%" in text or "18.0" in text  # Mbappe p_golden_boot
