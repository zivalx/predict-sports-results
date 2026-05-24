from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.ingest.polymarket import ingest_outright_winner, ingest_top_scorer_market
from worldcup.models import OddsSnapshot, Team
from scripts.seed_competition import seed


@pytest.fixture
def fake_poly_collector():
    """Mimics connectors.polymarket.PolymarketCollector for outright winner."""
    collector = MagicMock()
    market = MagicMock()
    market.question = "Winner of FIFA World Cup 2026"
    market.outcomes = ["Brazil", "France"]
    market.outcome_prices = [0.25, 0.18]
    market.volume = 100000.0
    result = MagicMock()
    result.status = "success"
    result.markets = [market]
    collector.fetch_markets = AsyncMock(return_value=result)
    return collector


@pytest.mark.asyncio
async def test_ingest_outright_persists_snapshot(fake_poly_collector):
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.commit()

    summary = await ingest_outright_winner(fake_poly_collector)
    assert summary["snapshots_inserted"] == 1
    assert summary["teams_matched"] == 2

    async with get_session() as session:
        snaps = (await session.execute(select(OddsSnapshot))).scalars().all()
    assert len(snaps) == 1
    assert snaps[0].market_type == "outright_winner"
    assert pytest.approx(snaps[0].outcomes["Brazil"], rel=1e-6) == 0.25
    assert pytest.approx(snaps[0].outcomes["France"], rel=1e-6) == 0.18


@pytest.mark.asyncio
async def test_ingest_outright_handles_no_match(fake_poly_collector):
    fake_poly_collector.fetch_markets.return_value.status = "success"
    fake_poly_collector.fetch_markets.return_value.markets = []

    await init_db()
    await seed()

    summary = await ingest_outright_winner(fake_poly_collector)
    assert summary == {"snapshots_inserted": 0, "teams_matched": 0}


@pytest.fixture
def fake_poly_topscorer_collector():
    collector = MagicMock()
    market = MagicMock()
    market.question = "Top Scorer of FIFA World Cup 2026"
    market.outcomes = ["Mbappe", "Haaland", "Vinicius Jr."]
    market.outcome_prices = [0.18, 0.14, 0.11]
    market.volume = 50000.0
    result = MagicMock()
    result.status = "success"
    result.markets = [market]
    collector.fetch_markets = AsyncMock(return_value=result)
    return collector


@pytest.mark.asyncio
async def test_ingest_top_scorer_persists_snapshot(fake_poly_topscorer_collector):
    await init_db()
    await seed()

    summary = await ingest_top_scorer_market(fake_poly_topscorer_collector)
    assert summary["snapshots_inserted"] == 1
    assert summary["outcomes_recorded"] == 3

    async with get_session() as session:
        snaps = (await session.execute(
            select(OddsSnapshot).where(OddsSnapshot.market_type == "top_scorer")
        )).scalars().all()
    assert len(snaps) == 1
    assert pytest.approx(snaps[0].outcomes["Mbappe"], rel=1e-6) == 0.18


@pytest.mark.asyncio
async def test_ingest_top_scorer_handles_missing_market(fake_poly_topscorer_collector):
    # Return an outright market instead — should not match the top-scorer filter
    fake_poly_topscorer_collector.fetch_markets.return_value.markets[0].question = (
        "Winner of FIFA World Cup 2026"
    )

    await init_db()
    await seed()

    summary = await ingest_top_scorer_market(fake_poly_topscorer_collector)
    assert summary == {"snapshots_inserted": 0, "outcomes_recorded": 0}
