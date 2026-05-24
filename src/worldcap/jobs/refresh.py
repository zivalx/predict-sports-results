from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.enrich.aggregate import aggregate_team_sentiment
from worldcap.enrich.claude_client import TokenBudgetExceeded
from worldcap.enrich.sentiment import score_unscored_items
from worldcap.ingest.fixtures import ingest_teams_and_fixtures
from worldcap.ingest.news import ingest_news_for_teams
from worldcap.ingest.players import load_seed_players
from worldcap.ingest.polymarket import ingest_outright_winner, ingest_top_scorer_market
from worldcap.ingest.reddit import ingest_reddit_for_competition
from worldcap.ingest.results import ingest_completed_results
from worldcap.log import get_logger
from worldcap.model.elo_updates import apply_elo_updates
from worldcap.model.per_match import generate_match_forecasts
from worldcap.model.ratings import load_seed_ratings
from worldcap.model.simulated_forecast import generate_simulated_forecast
from worldcap.model.top_scorer_forecast import generate_top_scorer_forecast
from worldcap.models import Competition, MatchForecast
from worldcap.models.forecast import ForecastSnapshot
from worldcap.rationale.match import generate_rationale_for_match
from worldcap.render.markdown import render_digest_markdown
from worldcap.render.writer import write_digest


log = get_logger(__name__)


async def run_refresh(
    trigger: str,
    football_client,
    poly_collector,
    *,
    gnews_collector=None,
    reddit_collector=None,
    claude_client=None,
    as_of: Optional[datetime] = None,
    competition_id: Optional[int] = None,
) -> ForecastSnapshot:
    """End-to-end pipeline."""
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

    players_summary = await load_seed_players()
    log.info("players.seed", **players_summary)

    elo_summary = await apply_elo_updates(results_summary["match_ids"])
    log.info("elo.updates", **elo_summary)

    if gnews_collector is not None:
        news_summary = await ingest_news_for_teams(gnews_collector)
        log.info("ingest.news", **news_summary)
    else:
        log.warning("ingest.news.skipped_no_collector")

    if reddit_collector is not None:
        reddit_summary = await ingest_reddit_for_competition(reddit_collector)
        log.info("ingest.reddit", **reddit_summary)
    else:
        log.warning("ingest.reddit.skipped_no_collector")

    if claude_client is not None and not claude_client.is_disabled():
        sentiment_summary = await score_unscored_items(claude_client, limit=50)
        log.info("sentiment.score", **sentiment_summary)
        agg_summary = await aggregate_team_sentiment(as_of=as_of, lookback_hours=72)
        log.info("sentiment.aggregate", **agg_summary)
    else:
        log.warning("sentiment.skipped_no_or_disabled_claude")

    odds_summary = await ingest_outright_winner(poly_collector)
    log.info("ingest.polymarket", **odds_summary)

    top_scorer_market_summary = await ingest_top_scorer_market(poly_collector)
    log.info("ingest.polymarket.top_scorer", **top_scorer_market_summary)

    snap, sim_result = await generate_simulated_forecast(trigger=trigger, n_iterations=2_000)
    log.info("forecast.tournament", snapshot_id=snap.id, model_version=snap.model_version)

    per_match_summary = await generate_match_forecasts(snapshot_id=snap.id, as_of=as_of)
    log.info("forecast.per_match", snapshot_id=snap.id, **per_match_summary)

    if sim_result is not None:
        ts_summary = await generate_top_scorer_forecast(snap.id, sim_result)
        log.info("forecast.top_scorer", **ts_summary)
    else:
        log.warning("forecast.top_scorer.skipped_no_sim_result")

    if claude_client is not None and not claude_client.is_disabled():
        try:
            async with get_session() as session:
                match_forecasts = (await session.execute(
                    select(MatchForecast).where(MatchForecast.snapshot_id == snap.id)
                )).scalars().all()
            rationale_count = 0
            for mf in match_forecasts:
                try:
                    result = await generate_rationale_for_match(claude_client, match_forecast_id=mf.id)
                    if result.get("rationale_written"):
                        rationale_count += 1
                except TokenBudgetExceeded:
                    log.warning("rationale.budget_exceeded", written_before_stop=rationale_count)
                    break
            log.info("rationale.batch", rationales_written=rationale_count)
        except Exception as exc:  # noqa: BLE001
            log.warning("rationale.block_failed", error=str(exc))
    else:
        log.warning("rationale.skipped_no_or_disabled_claude")

    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
    path = await write_digest(text, date_str=as_of.strftime("%Y-%m-%d"))
    log.info("render.digest", path=str(path))

    return snap
