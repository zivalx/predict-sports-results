"""Scrape per-match 3-way odds from Polymarket's sports World Cup pages.

For each upcoming match, constructs a Polymarket slug, fetches the match page,
and extracts home-win / draw / away-win probabilities from the embedded
``__NEXT_DATA__`` JSON.

The public sports pages embed a ``<script id="__NEXT_DATA__">`` blob that
contains dehydrated React-Query state with full event + markets data.  We
parse that JSON, locate the three moneyline markets (home / draw / away),
and read the ``outcomePrices[0]`` ("Yes" probability) from each.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func as sa_func
from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.log import get_logger
from worldcup.models import Competition, ForecastSnapshot, Match, MatchForecast, Team

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Country-code mapping  (our DB code -> Polymarket lowercase slug code)
# ---------------------------------------------------------------------------
# Most codes are simply lowercased.  The overrides handle FIFA trigrams that
# differ from Polymarket's ISO-ish slugs.
_PM_CODE_OVERRIDES: dict[str, str] = {
    "COD": "cdr",  # Congo DR
    "CPV": "cvi",  # Cape Verde
    "CRO": "hrv",  # Croatia
    "NED": "nld",  # Netherlands
    "POR": "prt",  # Portugal
    "SUI": "che",  # Switzerland
}

# South Korea uses "kr" in some slugs and "kor" in others on Polymarket.
# We try the shorter form first, then fallback.
_KOR_ALTERNATIVES = ("kr", "kor")


def _to_pm_code(country_code: str) -> str:
    """Map our DB ``country_code`` to a Polymarket slug fragment."""
    if country_code == "KOR":
        return _KOR_ALTERNATIVES[0]  # caller handles fallback
    return _PM_CODE_OVERRIDES.get(country_code, country_code.lower())


def _build_slug_candidates(
    home_code: str,
    away_code: str,
    kickoff: datetime,
) -> list[str]:
    """Return candidate Polymarket slugs to try, in priority order.

    Handles KOR alternate codes and home/away flip.
    """
    date_str = kickoff.strftime("%Y-%m-%d")
    home_variants = list(_KOR_ALTERNATIVES) if home_code == "KOR" else [_to_pm_code(home_code)]
    away_variants = list(_KOR_ALTERNATIVES) if away_code == "KOR" else [_to_pm_code(away_code)]

    candidates: list[str] = []
    # Natural order first (home-away)
    for hv in home_variants:
        for av in away_variants:
            candidates.append(f"fifwc-{hv}-{av}-{date_str}")
    # Swapped order (away-home)
    for av in away_variants:
        for hv in home_variants:
            slug = f"fifwc-{av}-{hv}-{date_str}"
            if slug not in candidates:
                candidates.append(slug)
    return candidates


# ---------------------------------------------------------------------------
# HTML / JSON parsing
# ---------------------------------------------------------------------------
_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _extract_next_data(html: str) -> Optional[dict]:
    """Pull the ``__NEXT_DATA__`` JSON from the page HTML."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _find_event_data(next_data: dict, slug: str) -> Optional[dict]:
    """Locate the dehydrated query whose key matches ``/api/event/slug``."""
    try:
        queries = next_data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        return None

    for q in queries:
        qk = q.get("queryKey", [])
        if len(qk) >= 2 and qk[0] == "/api/event/slug" and qk[1] == slug:
            return q.get("state", {}).get("data")
    return None


def _extract_three_way(
    event: dict,
    home_pm_code: str,
    away_pm_code: str,
) -> Optional[dict[str, float]]:
    """From the event data, extract 3-way moneyline probabilities.

    Returns ``{"home": float, "draw": float, "away": float}`` or ``None``.
    """
    markets = event.get("markets") or []
    event_slug = event.get("slug", "")

    probs: dict[str, Optional[float]] = {"home": None, "draw": None, "away": None}

    for mkt in markets:
        mkt_slug = mkt.get("slug", "")
        outcome_prices = mkt.get("outcomePrices")
        if not outcome_prices or not isinstance(outcome_prices, list):
            continue
        # outcomePrices is a list of strings like ['0.585', '0.415']
        # Index 0 is the "Yes" probability
        try:
            yes_prob = float(outcome_prices[0])
        except (ValueError, IndexError):
            continue

        if mkt_slug == f"{event_slug}-{home_pm_code}":
            probs["home"] = yes_prob
        elif mkt_slug == f"{event_slug}-draw":
            probs["draw"] = yes_prob
        elif mkt_slug == f"{event_slug}-{away_pm_code}":
            probs["away"] = yes_prob

    if all(v is not None for v in probs.values()):
        return {k: v for k, v in probs.items()}  # type: ignore[misc]

    return None


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------
_SCRAPE_HORIZON_DAYS = 14
_REQUEST_DELAY_S = 0.5


async def ingest_per_match_polymarket(
    *,
    horizon_days: int = _SCRAPE_HORIZON_DAYS,
) -> dict:
    """Scrape Polymarket per-match pages and update MatchForecast rows.

    Only processes SCHEDULED matches within *horizon_days* that already have
    a ``MatchForecast`` row in the latest snapshot.

    Returns summary dict with counts of updated / skipped / errored matches.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=horizon_days)
    updated = 0
    skipped = 0
    errored = 0

    async with get_session() as session:
        # Find latest snapshot
        comp = (
            await session.execute(
                select(Competition).where(
                    Competition.code == get_settings().db_competition_code,
                )
            )
        ).scalar_one()

        latest_snap = (
            await session.execute(
                select(ForecastSnapshot)
                .where(ForecastSnapshot.competition_id == comp.id)
                .order_by(ForecastSnapshot.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            )
        ).scalar_one_or_none()

        if latest_snap is None:
            log.warning("polymarket_matches.no_snapshot")
            return {"updated": 0, "skipped": 0, "errored": 0, "reason": "no_snapshot"}

        # Fetch scheduled matches in horizon with both teams known
        rows = (
            await session.execute(
                select(Match, MatchForecast)
                .join(MatchForecast, MatchForecast.match_id == Match.id)
                .where(MatchForecast.snapshot_id == latest_snap.id)
                .where(Match.kickoff_utc >= now)
                .where(Match.kickoff_utc <= cutoff)
                .where(Match.status == "SCHEDULED")
                .where(Match.home_team_id.is_not(None))
                .where(Match.away_team_id.is_not(None))
            )
        ).all()

        if not rows:
            log.info("polymarket_matches.no_upcoming_matches")
            return {"updated": 0, "skipped": 0, "errored": 0}

        # Bulk-load team codes
        team_ids = set()
        for match, _ in rows:
            team_ids.add(match.home_team_id)
            team_ids.add(match.away_team_id)

        teams = (
            await session.execute(select(Team).where(Team.id.in_(team_ids)))  # type: ignore[union-attr]
        ).scalars().all()
        team_map: dict[int, Team] = {t.id: t for t in teams}  # type: ignore[misc]

    # Now scrape outside the DB session
    results: list[tuple[int, dict[str, float]]] = []  # (forecast_id, probs)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0),
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        for match, forecast in rows:
            home_team = team_map.get(match.home_team_id)
            away_team = team_map.get(match.away_team_id)
            if not home_team or not away_team:
                skipped += 1
                continue
            home_code = home_team.country_code
            away_code = away_team.country_code
            if not home_code or not away_code:
                skipped += 1
                continue

            slugs = _build_slug_candidates(home_code, away_code, match.kickoff_utc)
            probs = None

            for slug in slugs:
                try:
                    url = f"https://polymarket.com/sports/world-cup/{slug}"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue

                    next_data = _extract_next_data(resp.text)
                    if next_data is None:
                        continue

                    event = _find_event_data(next_data, slug)
                    if event is None:
                        continue

                    # Determine the pm codes used in this slug
                    # slug format: fifwc-{home_pm}-{away_pm}-{date}
                    parts = slug.split("-")
                    # parts = ["fifwc", home_pm, away_pm, YYYY, MM, DD]
                    slug_home_pm = parts[1]
                    slug_away_pm = parts[2]

                    probs = _extract_three_way(event, slug_home_pm, slug_away_pm)
                    if probs is not None:
                        # If slug was swapped (away-home order), flip the probs
                        natural_home = _to_pm_code(home_code)
                        if home_code == "KOR":
                            natural_homes = set(_KOR_ALTERNATIVES)
                        else:
                            natural_homes = {natural_home}
                        if slug_home_pm not in natural_homes:
                            # Slug is swapped — swap home/away probs
                            probs["home"], probs["away"] = probs["away"], probs["home"]
                        break

                except Exception:
                    log.exception(
                        "polymarket_matches.slug_error",
                        slug=slug,
                        match_id=match.id,
                    )
                    continue

            if probs is not None:
                results.append((forecast.id, probs))  # type: ignore[union-attr]
                updated += 1
                log.info(
                    "polymarket_matches.scraped",
                    match_id=match.id,
                    home=home_code,
                    away=away_code,
                    p_home=probs["home"],
                    p_draw=probs["draw"],
                    p_away=probs["away"],
                )
            else:
                skipped += 1
                log.info(
                    "polymarket_matches.not_found",
                    match_id=match.id,
                    home=home_code,
                    away=away_code,
                )

            await asyncio.sleep(_REQUEST_DELAY_S)

    # Batch-update forecasts
    if results:
        async with get_session() as session:
            for forecast_id, probs in results:
                fc = (
                    await session.execute(
                        select(MatchForecast).where(MatchForecast.id == forecast_id)
                    )
                ).scalar_one()
                fc.p_home_poly = probs["home"]
                fc.p_draw_poly = probs["draw"]
                fc.p_away_poly = probs["away"]
                fc.edge_vs_poly = fc.p_home - probs["home"]
                session.add(fc)
            await session.commit()

    summary = {"updated": updated, "skipped": skipped, "errored": errored}
    log.info("polymarket_matches.done", **summary)
    return summary
