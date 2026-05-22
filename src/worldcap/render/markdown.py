from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import Team, TournamentForecast
from worldcap.models.forecast import ForecastSnapshot
from worldcap.models.tournament import Competition, Match


TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class OutlookRow:
    team_name: str
    p_champion: float
    poly_p_champion: float
    edge_vs_poly: float


@dataclass
class NextMatchRow:
    home_name: str
    away_name: str
    kickoff_utc: datetime
    group_label: str | None


def _phase_label(as_of: datetime, start_date: datetime, end_date: datetime) -> str:
    # Normalize to UTC for comparison if as_of is timezone-aware
    if as_of.tzinfo is not None:
        as_of_utc = as_of.replace(tzinfo=None) if as_of.tzinfo == timezone.utc else as_of.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        as_of_utc = as_of

    if as_of_utc < start_date:
        days = (start_date - as_of_utc).days
        return f"T−{days} days · pre-tournament"
    if as_of_utc <= end_date:
        return "in-tournament"
    return "post-tournament"


async def render_digest_markdown(snapshot_id: int, as_of: datetime, top_n: int = 10) -> str:
    async with get_session() as session:
        snap = (await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.id == snapshot_id)
        )).scalar_one()
        comp = (await session.execute(
            select(Competition).where(Competition.id == snap.competition_id)
        )).scalar_one()

        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snapshot_id)
            .order_by(TournamentForecast.p_champion.desc())
            .limit(top_n)
        )).scalars().all()
        teams_by_id = {
            t.id: t
            for t in (await session.execute(select(Team))).scalars().all()
        }
        outlook = [
            OutlookRow(
                team_name=teams_by_id[f.team_id].name,
                p_champion=f.p_champion,
                poly_p_champion=f.poly_p_champion or f.p_champion,
                edge_vs_poly=f.edge_vs_poly,
            )
            for f in forecasts
        ]

        upcoming = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .where(Match.status == "SCHEDULED")
            .where(Match.kickoff_utc >= as_of)
            .order_by(Match.kickoff_utc.asc())
            .limit(20)
        )).scalars().all()
        next_matches: list[NextMatchRow] = []
        for m in upcoming:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            next_matches.append(NextMatchRow(
                home_name=teams_by_id[m.home_team_id].name,
                away_name=teams_by_id[m.away_team_id].name,
                kickoff_utc=m.kickoff_utc,
                group_label=m.group_label,
            ))
            if len(next_matches) >= 3:
                break

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(disabled_extensions=("j2",)),
    )
    tmpl = env.get_template("digest_pretournament.md.j2")
    return tmpl.render(
        as_of=as_of,
        phase_label=_phase_label(as_of, comp.start_date, comp.end_date),
        outlook=outlook,
        next_matches=next_matches,
    )
