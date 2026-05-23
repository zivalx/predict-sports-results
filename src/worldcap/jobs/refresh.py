from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.ingest.fixtures import ingest_teams_and_fixtures
from worldcap.ingest.polymarket import ingest_outright_winner
from worldcap.ingest.results import ingest_completed_results
from worldcap.log import get_logger
from worldcap.model.elo_updates import apply_elo_updates
from worldcap.model.naive import generate_naive_forecast
from worldcap.model.per_match import generate_match_forecasts
from worldcap.model.ratings import load_seed_ratings
from worldcap.models import Competition
from worldcap.models.forecast import ForecastSnapshot
from worldcap.render.markdown import render_digest_markdown
from worldcap.render.writer import write_digest


log = get_logger(__name__)


async def run_refresh(
    trigger: str,
    football_client,
    poly_collector,
    as_of: Optional[datetime] = None,
    competition_id: Optional[int] = None,
) -> ForecastSnapshot:
    """End-to-end pipeline: ingest -> elo update -> forecasts -> render -> write."""

    as_of = as_of or datetime.now(timezone.utc)
    settings = get_settings()

    if competition_id is None:
        async with get_session() as session:
            comp = (await session.execute(
                select(Competition).where(Competition.code == settings.db_competition_code)
            )).scalar_one()
            competition_id = comp.id

    fixtures_summary = await ingest_teams_and_fixtures(football_client)
    log.info("ingest.fixtures", **fixtures_summary)

    results_summary = await ingest_completed_results(football_client)
    log.info("ingest.results", **results_summary)

    ratings_summary = await load_seed_ratings()
    log.info("ratings.seed", **ratings_summary)

    elo_summary = await apply_elo_updates(results_summary["match_ids"])
    log.info("elo.updates", **elo_summary)

    odds_summary = await ingest_outright_winner(poly_collector)
    log.info("ingest.polymarket", **odds_summary)

    snap = await generate_naive_forecast(trigger=trigger)
    log.info("forecast.naive", snapshot_id=snap.id, model_version=snap.model_version)

    per_match_summary = await generate_match_forecasts(snapshot_id=snap.id, as_of=as_of)
    log.info("forecast.per_match", snapshot_id=snap.id, **per_match_summary)

    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
    path = await write_digest(text, date_str=as_of.strftime("%Y-%m-%d"))
    log.info("render.digest", path=str(path))

    return snap
