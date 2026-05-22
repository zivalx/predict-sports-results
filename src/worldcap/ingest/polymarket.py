from datetime import datetime, timezone

from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import Competition, OddsSnapshot, Team

OUTRIGHT_QUERY = "FIFA World Cup 2026 winner"


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

    spec = MarketCollectSpec(active=True, order="volume", ascending=False, limit=50)
    result = await collector.fetch_markets(spec)
    if result.status != "success" or not result.markets:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    market = _find_outright_winner_market(result.markets)
    if market is None:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    outcomes = {o: p for o, p in zip(market.outcomes, market.outcome_prices)}

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == "WC2026")
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
