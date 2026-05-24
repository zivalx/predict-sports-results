"""Persist TopScorerForecast rows from a SimulationResult.

Given a snapshot id and the simulation result that produced it, write one
TopScorerForecast row per watchlist Player. Looks up matching Polymarket
top-scorer odds by exact name (when present) and computes edge.
"""

from sqlmodel import select

from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.model.simulator.orchestrator import SimulationResult
from worldcap.models import ForecastSnapshot, OddsSnapshot, Player, TopScorerForecast


MODEL_VERSION = "top-scorer-v0"

log = get_logger(__name__)


async def generate_top_scorer_forecast(
    snapshot_id: int,
    sim_result: SimulationResult,
) -> dict[str, int]:
    """Write TopScorerForecast rows for every watchlist player.

    Returns {"rows_written": int, "with_poly": int}.
    """
    rows_written = 0
    with_poly = 0

    async with get_session() as session:
        snap = (await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.id == snapshot_id)
        )).scalar_one()

        players = (await session.execute(
            select(Player).where(Player.is_watchlist == True)
        )).scalars().all()

        poly = (await session.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.competition_id == snap.competition_id)
            .where(OddsSnapshot.market_type == "top_scorer")
            .order_by(OddsSnapshot.ts.desc())
        )).scalars().first()
        poly_by_name: dict[str, float] = dict(poly.outcomes) if poly else {}

        for p in players:
            p_golden = sim_result.p_top_scorer(p.id)
            expected = sim_result.expected_goals(p.id)
            poly_p = poly_by_name.get(p.name)
            edge = (p_golden - poly_p) if poly_p is not None else 0.0
            session.add(TopScorerForecast(
                snapshot_id=snapshot_id,
                player_id=p.id,
                p_golden_boot=p_golden,
                expected_goals=expected,
                poly_p_top_scorer=poly_p,
                edge_vs_poly=edge,
                model_version=MODEL_VERSION,
            ))
            rows_written += 1
            if poly_p is not None:
                with_poly += 1

        await session.commit()

    log.info("forecast.top_scorer", rows_written=rows_written, with_poly=with_poly)
    return {"rows_written": rows_written, "with_poly": with_poly}
