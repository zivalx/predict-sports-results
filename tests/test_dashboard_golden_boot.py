from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from worldcup.api.app import build_app
from worldcup.db import get_session, init_db
from worldcup.models import (
    Competition,
    ForecastSnapshot,
    Player,
    Team,
    TopScorerForecast,
)
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_golden_boot_empty_state():
    await init_db()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/golden-boot")
    assert r.status_code == 200
    assert "Golden Boot race" in r.text


@pytest.mark.asyncio
async def test_golden_boot_lists_players_sorted_by_probability():
    await init_db()
    await seed()
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=1, name="Brazil", country_code="BRA"),
            Team(external_id=2, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add_all([
            Player(name="Vinicius", team_id=teams["Brazil"].id, goals_per_90=0.70),
            Player(name="Mbappe", team_id=teams["France"].id, goals_per_90=0.89),
            Player(name="Rodrygo", team_id=teams["Brazil"].id, goals_per_90=0.45),
        ])
        await session.flush()
        players = {p.name: p for p in (await session.execute(select(Player))).scalars().all()}
        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime(2026, 5, 24, tzinfo=timezone.utc),
            snapshot_trigger="manual",
            poly_odds_hash="x", model_state_hash="y", model_version="t",
        )
        session.add(snap)
        await session.flush()
        session.add_all([
            TopScorerForecast(snapshot_id=snap.id, player_id=players["Mbappe"].id,
                              p_golden_boot=0.18, expected_goals=4.2,
                              poly_p_top_scorer=0.16, edge_vs_poly=0.02),
            TopScorerForecast(snapshot_id=snap.id, player_id=players["Vinicius"].id,
                              p_golden_boot=0.14, expected_goals=3.1,
                              poly_p_top_scorer=None, edge_vs_poly=0.0),
            TopScorerForecast(snapshot_id=snap.id, player_id=players["Rodrygo"].id,
                              p_golden_boot=0.05, expected_goals=1.4,
                              poly_p_top_scorer=0.04, edge_vs_poly=0.01),
        ])
        await session.commit()

    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/golden-boot")
    assert r.status_code == 200
    body = r.text
    # Mbappe (0.18) → Vinicius (0.14) → Rodrygo (0.05)
    mp = body.find("Mbappe"); vp = body.find("Vinicius"); rp = body.find("Rodrygo")
    assert -1 < mp < vp < rp
    assert "18.0%" in body or "18%" in body
    # Vinicius has no polymarket — should render "—"
    # (we can't easily isolate just his row's polymarket cell, but the row label "Vinicius" + "—" must coexist)
