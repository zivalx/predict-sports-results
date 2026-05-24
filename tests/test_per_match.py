from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.model.elo import HOME_ADVANTAGE
from worldcap.model.per_match import generate_match_forecasts
from worldcap.models import (
    ForecastSnapshot,
    Match,
    MatchForecast,
    Team,
    TeamRating,
)
from worldcap.models.tournament import Competition
from scripts.seed_competition import seed


async def _setup(as_of: datetime):
    """Helper: seed competition, 2 teams with ratings, one match in 7 days."""
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
        session.add_all([
            TeamRating(team_id=teams["Brazil"].id, rating=1790.0,
                       last_updated=as_of, source="seed"),
            TeamRating(team_id=teams["France"].id, rating=1830.0,
                       last_updated=as_of, source="seed"),
        ])
        session.add(Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=as_of + timedelta(days=7),
            status="SCHEDULED",
        ))
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=as_of,
            snapshot_trigger="manual",
            poly_odds_hash="x",
            model_version="elo-v0",
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)
        return snap.id


@pytest.mark.asyncio
async def test_generates_one_forecast_per_eligible_match():
    as_of = datetime(2026, 5, 22, tzinfo=timezone.utc)
    snap_id = await _setup(as_of)

    summary = await generate_match_forecasts(
        snapshot_id=snap_id,
        as_of=as_of,
    )
    assert summary == {"forecasts_written": 1, "matches_skipped_unrated": 0}

    async with get_session() as session:
        rows = (await session.execute(
            select(MatchForecast).where(MatchForecast.snapshot_id == snap_id)
        )).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.p_home + row.p_draw + row.p_away == pytest.approx(1.0, abs=1e-9)
    # France (1830) is stronger than Brazil (1790) but Brazil is at home with +100 advantage
    # → Brazil should be the favorite.
    assert row.p_home > row.p_away
    assert row.p_home_poly is None
    assert row.p_draw_poly is None
    assert row.p_away_poly is None


@pytest.mark.asyncio
async def test_generates_forecast_for_match_far_in_future():
    """A match 60 days out should still get a MatchForecast row (no horizon cap)."""
    as_of = datetime(2026, 5, 22, tzinfo=timezone.utc)
    # Rebuild setup but with a match 60 days out instead of 7.
    await init_db()
    await seed()
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=761, name="Argentina", country_code="ARG"),
            Team(external_id=762, name="Germany", country_code="GER"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add_all([
            TeamRating(team_id=teams["Argentina"].id, rating=1820.0,
                       last_updated=as_of, source="seed"),
            TeamRating(team_id=teams["Germany"].id, rating=1800.0,
                       last_updated=as_of, source="seed"),
        ])
        session.add(Match(
            external_id=2,
            competition_id=comp.id,
            stage="group",
            group_label="B",
            home_team_id=teams["Argentina"].id,
            away_team_id=teams["Germany"].id,
            kickoff_utc=as_of + timedelta(days=60),
            status="SCHEDULED",
        ))
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=as_of,
            snapshot_trigger="manual",
            poly_odds_hash="y",
            model_version="elo-v0",
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)
        snap_id = snap.id

    summary = await generate_match_forecasts(snapshot_id=snap_id, as_of=as_of)
    assert summary["forecasts_written"] == 1
    assert summary["matches_skipped_unrated"] == 0

    async with get_session() as session:
        rows = (await session.execute(
            select(MatchForecast).where(MatchForecast.snapshot_id == snap_id)
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].p_home + rows[0].p_draw + rows[0].p_away == pytest.approx(1.0, abs=1e-9)


@pytest.mark.asyncio
async def test_skips_matches_with_missing_team_rating():
    as_of = datetime(2026, 5, 22, tzinfo=timezone.utc)
    snap_id = await _setup(as_of)

    # Delete Brazil's rating.
    async with get_session() as session:
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        ratings = (await session.execute(select(TeamRating).where(TeamRating.team_id == teams["Brazil"].id))).scalars().all()
        for r in ratings:
            await session.delete(r)
        await session.commit()

    summary = await generate_match_forecasts(
        snapshot_id=snap_id,
        as_of=as_of,
    )
    assert summary["forecasts_written"] == 0
    assert summary["matches_skipped_unrated"] == 1


@pytest.mark.asyncio
async def test_skips_matches_with_no_teams_resolved():
    as_of = datetime(2026, 5, 22, tzinfo=timezone.utc)
    snap_id = await _setup(as_of)

    # Insert a "slot" match (knockout TBD) with no teams.
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(Match(
            external_id=999,
            competition_id=comp.id,
            stage="R16",
            group_label=None,
            home_team_id=None,
            away_team_id=None,
            kickoff_utc=as_of + timedelta(days=5),
            status="SCHEDULED",
        ))
        await session.commit()

    summary = await generate_match_forecasts(
        snapshot_id=snap_id,
        as_of=as_of,
    )
    # Still 1 forecast (the BRA-FRA match), the slot match is silently skipped.
    assert summary["forecasts_written"] == 1
