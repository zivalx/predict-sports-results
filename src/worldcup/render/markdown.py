from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import select

from worldcup.db import get_session
from worldcup.models import Team, TournamentForecast, Player, TopScorerForecast
from worldcup.models.forecast import ForecastSnapshot, MatchForecast
from worldcup.models.tournament import Competition, Match


TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class OutlookRow:
    team_name: str
    p_champion: float
    poly_p_champion: float
    edge_vs_poly: float


@dataclass
class MatchForecastRow:
    home_name: str
    away_name: str
    kickoff_utc: datetime
    group_label: str | None
    stage: str
    p_home: float
    p_draw: float
    p_away: float
    p_home_poly: float | None
    p_draw_poly: float | None
    p_away_poly: float | None
    edge_vs_poly: float
    rationale_md: str | None


@dataclass
class NextMatchRow:
    home_name: str
    away_name: str
    kickoff_utc: datetime
    group_label: str | None


@dataclass
class TopScorerRow:
    player_name: str
    team_name: str
    p_golden_boot: float
    poly_p_top_scorer: float | None
    edge_vs_poly: float
    goals_per_90: float


def _phase_label(as_of: datetime, start_date: datetime, end_date: datetime) -> str:
    # Normalise comparison to UTC; SQLite strips tzinfo on round-trip for DateTime columns.
    def _to_naive_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    a = _to_naive_utc(as_of)
    s = _to_naive_utc(start_date)
    e = _to_naive_utc(end_date)
    if a < s:
        days = (s - a).days
        return f"T−{days} days · pre-tournament"
    if a <= e:
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

        # Top-scorer race (top 10 by p_golden_boot)
        top_scorer_rows_raw = (await session.execute(
            select(TopScorerForecast, Player, Team)
            .join(Player, TopScorerForecast.player_id == Player.id)
            .join(Team, Player.team_id == Team.id)
            .where(TopScorerForecast.snapshot_id == snapshot_id)
            .order_by(TopScorerForecast.p_golden_boot.desc())
            .limit(10)
        )).all()
        top_scorers = [
            TopScorerRow(
                player_name=player.name,
                team_name=team.name,
                p_golden_boot=tsf.p_golden_boot,
                poly_p_top_scorer=tsf.poly_p_top_scorer,
                edge_vs_poly=tsf.edge_vs_poly,
                goals_per_90=player.goals_per_90,
            )
            for tsf, player, team in top_scorer_rows_raw
        ]

        # Per-match forecasts (joined to Match for kickoff + group_label + teams)
        per_match_rows = (await session.execute(
            select(MatchForecast, Match)
            .join(Match, MatchForecast.match_id == Match.id)
            .where(MatchForecast.snapshot_id == snapshot_id)
            .order_by(Match.kickoff_utc.asc())
        )).all()
        per_match: list[MatchForecastRow] = []
        for mf, m in per_match_rows:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            per_match.append(MatchForecastRow(
                home_name=teams_by_id[m.home_team_id].name,
                away_name=teams_by_id[m.away_team_id].name,
                kickoff_utc=m.kickoff_utc,
                group_label=m.group_label,
                stage=m.stage,
                p_home=mf.p_home,
                p_draw=mf.p_draw,
                p_away=mf.p_away,
                p_home_poly=mf.p_home_poly,
                p_draw_poly=mf.p_draw_poly,
                p_away_poly=mf.p_away_poly,
                edge_vs_poly=mf.edge_vs_poly,
                rationale_md=mf.rationale_md,
            ))

        # Next 3 upcoming fixtures (still useful for "what's next" when as_of is far before kickoff)
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
        top_scorers=top_scorers,
        per_match=per_match,
        next_matches=next_matches,
    )
