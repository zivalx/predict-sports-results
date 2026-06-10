import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_mcp import FastApiMCP
from sqlmodel import select

from worldcup.api.dashboard import router as dashboard_router
from worldcup.api.mcp_endpoints import mcp_router
from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.jobs.refresh import run_refresh
from worldcup.jobs.scheduler import build_scheduler
from worldcup.log import configure_logging, get_logger
from worldcup.models import Competition, ForecastSnapshot, Team, TournamentForecast


log = get_logger(__name__)


def _default_clients():
    """Production client builders. Imported lazily so tests don't need real keys.

    Returns: (football, poly, gnews_or_none, reddit_or_none, claude_or_none)
    Clients whose required env vars are unset come back as None and the
    pipeline will skip the corresponding step with a warning log.
    """
    from connectors.polymarket import PolymarketClientConfig, PolymarketCollector

    from worldcup.enrich.claude_client import ClaudeClient
    from worldcup.ingest.sports_data import FootballDataClient

    settings = get_settings()
    football = FootballDataClient(api_key=settings.football_data_api_key)
    poly = PolymarketCollector(PolymarketClientConfig(timeout=30))

    gnews = None
    if settings.gnews_api_key:
        try:
            from connectors.gnews import GNewsCollector, GNewsClientConfig
            gnews = GNewsCollector(GNewsClientConfig(api_key=settings.gnews_api_key))
        except ImportError:
            pass  # connectors[gnews] extra not installed

    reddit = None
    if settings.reddit_client_id and settings.reddit_client_secret:
        try:
            from connectors.reddit import RedditCollector, RedditClientConfig
            reddit = RedditCollector(RedditClientConfig(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            ))
        except ImportError:
            pass

    claude = None
    if settings.anthropic_api_key:
        claude = ClaudeClient(
            api_key=settings.anthropic_api_key,
            token_budget=settings.rationale_token_budget,
        )

    return football, poly, gnews, reddit, claude


def build_app(
    football_client=None,
    poly_collector=None,
    gnews_collector=None,
    reddit_collector=None,
    claude_client=None,
) -> FastAPI:
    configure_logging()

    if football_client is None or poly_collector is None:
        football_client, poly_collector, _gnews_default, _reddit_default, _claude_default = _default_clients()
        if gnews_collector is None:
            gnews_collector = _gnews_default
        if reddit_collector is None:
            reddit_collector = _reddit_default
        if claude_client is None:
            claude_client = _claude_default

    async def _trigger_refresh(trigger: str = "manual"):
        return await run_refresh(
            trigger=trigger,
            football_client=football_client,
            poly_collector=poly_collector,
            gnews_collector=gnews_collector,
            reddit_collector=reddit_collector,
            claude_client=claude_client,
            as_of=datetime.now(timezone.utc),
        )

    # Coroutine-function wrappers for APScheduler. A bare `lambda: _trigger_refresh(...)`
    # returns a coroutine that APScheduler doesn't await; using `async def` wrappers
    # makes them proper coroutine functions that the scheduler invokes correctly.
    async def _daily_refresh():
        await _trigger_refresh("daily")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Daily-only mode. To enable a post-match interval trigger, pass
        # `post_match_fn=_some_async_fn` to build_scheduler() below.
        scheduler = build_scheduler(refresh_fn=_daily_refresh)
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            if hasattr(football_client, "aclose"):
                await football_client.aclose()

    app = FastAPI(title="worldcup", lifespan=lifespan)

    # Static files and templates
    _this_dir = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=_this_dir / "static"), name="static")
    templates = Jinja2Templates(directory=_this_dir / "templates")
    app.state.templates = templates

    # Dashboard routes
    app.include_router(dashboard_router)

    # MCP-friendly JSON endpoints
    app.include_router(mcp_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/refresh")
    async def refresh():
        snap, refresh_result = await _trigger_refresh("manual")
        return {
            "snapshot_id": snap.id if snap else None,
            "trigger": snap.snapshot_trigger if snap else "manual",
            "ok": refresh_result.ok,
            "steps": [s.to_dict() for s in refresh_result.steps],
        }

    @app.get("/api/refresh_status")
    async def refresh_status():
        from worldcup.jobs import refresh as refresh_mod
        rr = refresh_mod.last_refresh_result
        if rr is None:
            return {"last_refresh": None}
        return {"last_refresh": rr.to_dict()}

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

    # Mount MCP server — auto-exposes API endpoints as MCP tools
    mcp = FastApiMCP(app, name="worldcup", description="World Cup 2026 forecasts and analysis")
    mcp.mount_http()

    return app


# Module-level `app` for `uvicorn worldcup.api.app:app`. Skipped when tests / alembic
# import the module — controlled by WORLDCUP_SKIP_DEFAULT_APP.
if os.environ.get("WORLDCUP_SKIP_DEFAULT_APP") == "1":
    app = None
else:
    try:
        app = build_app()
    except Exception:  # noqa: BLE001 — don't crash imports if creds missing
        app = None
