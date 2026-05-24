from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from worldcap.api.app import build_app


@pytest.mark.asyncio
async def test_static_css_served():
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/static/dashboard.css")
    assert r.status_code == 200
    assert "body" in r.text  # css is body-styled
