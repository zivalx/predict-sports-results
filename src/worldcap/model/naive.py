import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    OddsSnapshot,
    Team,
    TournamentForecast,
)


def _state_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


async def generate_naive_forecast(trigger: str = "manual") -> ForecastSnapshot:
    """Write a ForecastSnapshot whose tournament-level probabilities are the latest
    Polymarket outright-winner odds, mapped onto Team rows. edge_vs_poly is 0.
    Returns the persisted ForecastSnapshot."""

    async with get_session() as session:
        comp = (await session.execute(select(Competition).where(Competition.code == get_settings().db_competition_code))).scalar_one()

        latest = (await session.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.competition_id == comp.id)
            .where(OddsSnapshot.market_type == "outright_winner")
            .order_by(OddsSnapshot.ts.desc())
        )).scalars().first()

        if latest is None:
            outcomes: dict[str, float] = {}
        else:
            outcomes = dict(latest.outcomes)

        teams = (await session.execute(select(Team))).scalars().all()
        team_by_name = {t.name: t for t in teams}

        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime.now(timezone.utc),
            snapshot_trigger=trigger,
            poly_odds_hash=_state_hash(outcomes),
            model_version="naive-poly-only-v0",
        )
        session.add(snap)
        await session.flush()

        for name, p in outcomes.items():
            team = team_by_name.get(name)
            if team is None:
                continue
            session.add(TournamentForecast(
                snapshot_id=snap.id,
                team_id=team.id,
                p_champion=float(p),
                poly_p_champion=float(p),
                edge_vs_poly=0.0,
            ))

        await session.commit()
        await session.refresh(snap)
        return snap
