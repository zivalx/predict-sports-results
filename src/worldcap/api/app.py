import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.jobs.refresh import run_refresh
from worldcap.jobs.scheduler import build_scheduler
from worldcap.log import configure_logging, get_logger
from worldcap.models import Competition, ForecastSnapshot, Team, TournamentForecast


log = get_logger(__name__)


def _default_clients():
    """Production client builders. Imported lazily so tests don't need real keys."""
    from connectors.polymarket import PolymarketClientConfig, PolymarketCollector

    from worldcap.ingest.sports_data import FootballDataClient

    settings = get_settings()
    football = FootballDataClient(api_key=settings.football_data_api_key)
    poly = PolymarketCollector(PolymarketClientConfig(timeout=30))
    return football, poly


def build_app(football_client=None, poly_collector=None) -> FastAPI:
    configure_logging()

    if football_client is None or poly_collector is None:
        football_client, poly_collector = _default_clients()

    async def _trigger_refresh(trigger: str = "manual"):
        return await run_refresh(
            trigger=trigger,
            football_client=football_client,
            poly_collector=poly_collector,
            as_of=datetime.now(timezone.utc),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = build_scheduler(refresh_fn=lambda: _trigger_refresh("daily"))
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            if hasattr(football_client, "aclose"):
                await football_client.aclose()

    app = FastAPI(title="worldcap", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/refresh")
    async def refresh():
        snap = await _trigger_refresh("manual")
        return {"snapshot_id": snap.id, "trigger": snap.snapshot_trigger}

    @app.get("/forecast/latest")
    async def forecast_latest():
        async with get_session() as session:
            comp = (await session.execute(
                select(Competition).where(Competition.code == get_settings().db_competition_code)
            )).scalar_one_or_none()
            if comp is None:
                return {"snapshot": None, "outlook": []}
            snap = (await session.execute(
                select(ForecastSnapshot)
                .where(ForecastSnapshot.competition_id == comp.id)
                .order_by(ForecastSnapshot.snapshot_date.desc())
            )).scalars().first()
            if snap is None:
                return {"snapshot": None, "outlook": []}
            forecasts = (await session.execute(
                select(TournamentForecast)
                .where(TournamentForecast.snapshot_id == snap.id)
                .order_by(TournamentForecast.p_champion.desc())
            )).scalars().all()
            teams_by_id = {
                t.id: t for t in (await session.execute(select(Team))).scalars().all()
            }
            return {
                "snapshot": {
                    "id": snap.id,
                    "snapshot_date": snap.snapshot_date.isoformat(),
                    "trigger": snap.snapshot_trigger,
                    "model_version": snap.model_version,
                },
                "outlook": [
                    {
                        "team": teams_by_id[f.team_id].name,
                        "p_champion": f.p_champion,
                        "poly_p_champion": f.poly_p_champion,
                        "edge_vs_poly": f.edge_vs_poly,
                    }
                    for f in forecasts
                ],
            }

    return app


# Module-level `app` for `uvicorn worldcap.api.app:app`. Skipped when tests / alembic
# import the module — controlled by WORLDCAP_SKIP_DEFAULT_APP.
if os.environ.get("WORLDCAP_SKIP_DEFAULT_APP") == "1":
    app = None
else:
    try:
        app = build_app()
    except Exception:  # noqa: BLE001 — don't crash imports if creds missing
        app = None
