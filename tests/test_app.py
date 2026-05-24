from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from worldcup.api.app import build_app
from worldcup.db import init_db
from scripts.seed_competition import seed


@pytest.fixture
def fake_clients():
    football = AsyncMock()
    football.get_teams.return_value = []
    football.get_fixtures.return_value = []
    poly_market = MagicMock()
    poly_market.question = "Winner of FIFA World Cup 2026"
    poly_market.outcomes = []
    poly_market.outcome_prices = []
    poly_market.volume = 0
    poly_result = MagicMock()
    poly_result.status = "success"
    poly_result.markets = [poly_market]
    poly = MagicMock()
    poly.fetch_markets = AsyncMock(return_value=poly_result)
    return football, poly


@pytest.mark.asyncio
async def test_healthz_ok():
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_post_refresh_runs_pipeline(fake_clients):
    await init_db()
    await seed()

    football, poly = fake_clients
    app = build_app(football_client=football, poly_collector=poly)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot_id"] >= 1
    assert body["trigger"] == "manual"
