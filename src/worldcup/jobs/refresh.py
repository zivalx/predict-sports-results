import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.enrich.aggregate import aggregate_team_sentiment
from worldcup.enrich.claude_client import TokenBudgetExceeded
from worldcup.enrich.sentiment import score_unscored_items
from worldcup.ingest.fixtures import ingest_teams_and_fixtures
from worldcup.ingest.news import ingest_news_for_teams
from worldcup.ingest.players import load_seed_players
from worldcup.ingest.polymarket import ingest_outright_winner, ingest_top_scorer_market
from worldcup.ingest.polymarket_matches import ingest_per_match_polymarket
from worldcup.ingest.reddit import ingest_reddit_for_competition
from worldcup.ingest.results import ingest_completed_results
from worldcup.log import get_logger
from worldcup.model.elo_updates import apply_elo_updates
from worldcup.model.per_match import generate_match_forecasts
from worldcup.model.ratings import load_seed_ratings
from worldcup.model.simulated_forecast import generate_simulated_forecast
from worldcup.model.top_scorer_forecast import generate_top_scorer_forecast
from worldcup.models import Competition, Match, MatchForecast
from worldcup.models.forecast import ForecastSnapshot
from worldcup.rationale.match import generate_rationale_for_match
from worldcup.render.markdown import render_digest_markdown
from worldcup.render.writer import write_digest


log = get_logger(__name__)


class StepResult:
    """Outcome of a single pipeline step."""
    __slots__ = ("name", "ok", "detail", "elapsed_s")

    def __init__(self, name: str, ok: bool, detail: str = "", elapsed_s: float = 0.0):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.elapsed_s = elapsed_s

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "elapsed_s": round(self.elapsed_s, 2)}


class RefreshResult:
    """Aggregated result of a full pipeline run."""

    def __init__(self, trigger: str, started_at: datetime):
        self.trigger = trigger
        self.started_at = started_at
        self.finished_at: Optional[datetime] = None
        self.snapshot_id: Optional[int] = None
        self.steps: list[StepResult] = []
        self.ok = True

    def add(self, step: StepResult):
        self.steps.append(step)
        if not step.ok:
            self.ok = False

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "ok": self.ok,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "snapshot_id": self.snapshot_id,
            "steps": [s.to_dict() for s in self.steps],
        }


# Module-level ref to the last refresh result — read by the /status page.
last_refresh_result: Optional[RefreshResult] = None


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
) -> tuple[Optional[ForecastSnapshot], RefreshResult]:
    """End-to-end pipeline. Returns (snapshot_or_none, refresh_result)."""
    global last_refresh_result
    as_of = as_of or datetime.now(timezone.utc)
    settings = get_settings()
    result = RefreshResult(trigger=trigger, started_at=as_of)

    async def _step(name: str, coro):
        """Run a pipeline step, track timing and success/failure."""
        t0 = time.monotonic()
        try:
            rv = await coro
            elapsed = time.monotonic() - t0
            detail = str(rv) if isinstance(rv, dict) else ""
            result.add(StepResult(name, ok=True, detail=detail, elapsed_s=elapsed))
            log.info(name, elapsed_s=round(elapsed, 2), **(rv if isinstance(rv, dict) else {}))
            return rv
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            result.add(StepResult(name, ok=False, detail=str(exc), elapsed_s=elapsed))
            log.warning(f"{name}.failed", error=str(exc), elapsed_s=round(elapsed, 2))
            return None

    if competition_id is None:
        async with get_session() as session:
            comp = (await session.execute(
                select(Competition).where(Competition.code == settings.db_competition_code)
            )).scalar_one()
            competition_id = comp.id

    # --- Ingest phase: each source is best-effort ---

    result_match_ids: list[int] = []

    await _step("ingest.fixtures", ingest_teams_and_fixtures(football_client))

    results_summary = await _step("ingest.results", ingest_completed_results(football_client))
    if isinstance(results_summary, dict):
        result_match_ids = results_summary.get("match_ids", [])

    await _step("ratings.seed", load_seed_ratings())
    await _step("players.seed", load_seed_players())
    await _step("elo.updates", apply_elo_updates(result_match_ids))

    if gnews_collector is not None:
        await _step("ingest.news", ingest_news_for_teams(gnews_collector))
    else:
        result.add(StepResult("ingest.news", ok=True, detail="skipped: no collector"))

    if reddit_collector is not None:
        await _step("ingest.reddit", ingest_reddit_for_competition(reddit_collector))
    else:
        result.add(StepResult("ingest.reddit", ok=True, detail="skipped: no collector"))

    if claude_client is not None and not claude_client.is_disabled():
        await _step("sentiment", score_unscored_items(claude_client, limit=50))
        await _step("sentiment.aggregate", aggregate_team_sentiment(as_of=as_of, lookback_hours=72))
    else:
        result.add(StepResult("sentiment", ok=True, detail="skipped: no claude"))

    await _step("ingest.polymarket", ingest_outright_winner(poly_collector))
    await _step("ingest.polymarket.top_scorer", ingest_top_scorer_market(poly_collector))

    # --- Forecast phase: simulator is critical, rest is best-effort ---

    snap = None
    sim_result = None

    sim_rv = await _step("forecast.tournament", generate_simulated_forecast(trigger=trigger, n_iterations=2_000))
    if sim_rv is not None:
        snap, sim_result = sim_rv

    if snap is not None:
        await _step("forecast.per_match", generate_match_forecasts(snapshot_id=snap.id, as_of=as_of))

        if sim_result is not None:
            await _step("forecast.top_scorer", generate_top_scorer_forecast(snap.id, sim_result))
        else:
            result.add(StepResult("forecast.top_scorer", ok=True, detail="skipped: no sim result"))

        # --- Polymarket per-match odds (scrapes match pages) ---
        await _step("ingest.polymarket.matches", ingest_per_match_polymarket())

        # --- Rationale phase ---
        if claude_client is not None and not claude_client.is_disabled():
            try:
                t0 = time.monotonic()
                horizon_end = as_of + timedelta(days=settings.rationale_horizon_days)
                async with get_session() as session:
                    rows = (await session.execute(
                        select(MatchForecast, Match)
                        .join(Match, MatchForecast.match_id == Match.id)
                        .where(MatchForecast.snapshot_id == snap.id)
                        .where(Match.kickoff_utc <= horizon_end)
                        .order_by(Match.kickoff_utc.asc())
                    )).all()
                match_forecasts = [mf for mf, _ in rows]
                rationale_count = 0
                for mf in match_forecasts:
                    try:
                        rv = await generate_rationale_for_match(claude_client, match_forecast_id=mf.id)
                        if rv.get("rationale_written"):
                            rationale_count += 1
                    except TokenBudgetExceeded:
                        log.warning("rationale.budget_exceeded", written_before_stop=rationale_count)
                        break
                elapsed = time.monotonic() - t0
                result.add(StepResult("rationale", ok=True, detail=f"{rationale_count} written", elapsed_s=elapsed))
                log.info("rationale.batch", rationales_written=rationale_count)
            except Exception as exc:  # noqa: BLE001
                elapsed = time.monotonic() - t0
                result.add(StepResult("rationale", ok=False, detail=str(exc), elapsed_s=elapsed))
                log.warning("rationale.failed", error=str(exc))
        else:
            result.add(StepResult("rationale", ok=True, detail="skipped: no claude"))

        # --- Render phase ---
        try:
            t0 = time.monotonic()
            text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
            path = await write_digest(text, date_str=as_of.strftime("%Y-%m-%d"))
            elapsed = time.monotonic() - t0
            result.add(StepResult("render.digest", ok=True, detail=str(path), elapsed_s=elapsed))
            log.info("render.digest", path=str(path))
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            result.add(StepResult("render.digest", ok=False, detail=str(exc), elapsed_s=elapsed))
            log.warning("render.digest.failed", error=str(exc))
    else:
        result.add(StepResult("forecast.tournament", ok=False, detail="no snapshot created — skipping downstream"))

    result.finished_at = datetime.now(timezone.utc)
    result.snapshot_id = snap.id if snap else None
    last_refresh_result = result
    return snap, result
