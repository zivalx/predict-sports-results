from datetime import datetime, timezone
from typing import Optional

from worldcap.config import get_settings
from worldcap.ingest.fixtures import ingest_teams_and_fixtures
from worldcap.ingest.polymarket import ingest_outright_winner
from worldcap.ingest.sports_data import FootballDataClient
from worldcap.log import get_logger
from worldcap.model.naive import generate_naive_forecast
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
    """End-to-end pipeline: ingest -> forecast -> render -> write. Returns the snapshot."""

    as_of = as_of or datetime.now(timezone.utc)

    # Lookup competition_id if not provided
    if competition_id is None:
        from sqlmodel import select
        from worldcap.db import get_session
        from worldcap.models import Competition
        settings = get_settings()
        async with get_session() as session:
            comp = (await session.execute(
                select(Competition).where(Competition.code == settings.db_competition_code)
            )).scalar_one()
            competition_id = comp.id

    fixtures_summary = await ingest_teams_and_fixtures(football_client)
    log.info("ingest.fixtures", **fixtures_summary)

    odds_summary = await ingest_outright_winner(poly_collector)
    log.info("ingest.polymarket", **odds_summary)

    snap = await generate_naive_forecast(trigger=trigger)
    log.info("forecast.naive", snapshot_id=snap.id, model_version=snap.model_version)

    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
    path = await write_digest(text, date_str=as_of.strftime("%Y-%m-%d"))
    log.info("render.digest", path=str(path))

    return snap
