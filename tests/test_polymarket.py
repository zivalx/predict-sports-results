from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.ingest.polymarket import ingest_outright_winner
from worldcap.models import OddsSnapshot, Team
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
