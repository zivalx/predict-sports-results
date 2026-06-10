from datetime import datetime, timezone

from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.models import Competition, OddsSnapshot, Team


def _find_outright_winner_market(markets):
    """Heuristic: the market whose question contains 'World Cup 2026' and 'winner'."""
    for m in markets:
        q = (m.question or "").lower()
        if "world cup 2026" in q and "winner" in q:
            return m
    return None


async def ingest_outright_winner(collector) -> dict[str, int]:
    """Pulls the WC 2026 outright winner market from Polymarket and writes one OddsSnapshot row."""
    from connectors.polymarket import MarketCollectSpec  # noqa: WPS433

    # Search specifically for World Cup markets instead of relying on top-50 by volume
    spec = MarketCollectSpec(query="world cup 2026 winner", active=True, order="volume", ascending=False, limit=50)
    result = await collector.fetch_markets(spec)
    if result.status != "success" or not result.markets:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    market = _find_outright_winner_market(result.markets)
    if market is None:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    outcomes = {o: p for o, p in zip(market.outcomes, market.outcome_prices)}

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == get_settings().db_competition_code)
        )).scalar_one()
        teams = (await session.execute(select(Team))).scalars().all()
        team_names = {t.name for t in teams}
        teams_matched = sum(1 for name in outcomes if name in team_names)

        snap = OddsSnapshot(
            competition_id=comp.id,
            match_id=None,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime.now(timezone.utc),
            outcomes=outcomes,
            volume=getattr(market, "volume", None),
        )
        session.add(snap)
        await session.commit()

    return {"snapshots_inserted": 1, "teams_matched": teams_matched}


def _find_top_scorer_market(markets):
    """Heuristic: market whose question contains 'World Cup 2026' AND
    ('top scorer' OR 'golden boot')."""
    for m in markets:
        q = (m.question or "").lower()
        if "world cup 2026" not in q:
            continue
        if "top scorer" in q or "golden boot" in q:
            return m
    return None


async def ingest_top_scorer_market(collector) -> dict[str, int]:
    """Pulls the WC 2026 top-scorer market from Polymarket and writes one OddsSnapshot row."""
    from connectors.polymarket import MarketCollectSpec  # noqa: WPS433

    spec = MarketCollectSpec(query="world cup 2026 top scorer", active=True, order="volume", ascending=False, limit=50)
    result = await collector.fetch_markets(spec)
    if result.status != "success" or not result.markets:
        return {"snapshots_inserted": 0, "outcomes_recorded": 0}

    market = _find_top_scorer_market(result.markets)
    if market is None:
        return {"snapshots_inserted": 0, "outcomes_recorded": 0}

    outcomes = {o: p for o, p in zip(market.outcomes, market.outcome_prices)}

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == get_settings().db_competition_code)
        )).scalar_one()
        snap = OddsSnapshot(
            competition_id=comp.id,
            match_id=None,
            market_type="top_scorer",
            source="polymarket",
            ts=datetime.now(timezone.utc),
            outcomes=outcomes,
            volume=getattr(market, "volume", None),
        )
        session.add(snap)
        await session.commit()

    return {"snapshots_inserted": 1, "outcomes_recorded": len(outcomes)}
