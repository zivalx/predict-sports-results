"""HTML routes for the worldcap dashboard.

Server-rendered Jinja2 templates. HTMX is used for the manual-refresh button
via a partial swap. All data flows from the latest ForecastSnapshot.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    Match,
    MatchForecast,
    NewsItem,
    Team,
    TournamentForecast,
)


router = APIRouter()


@dataclass
class TopContenderRow:
    rank: int
    team_name: str
    p_champion: float
    poly_p_champion: float
    edge_vs_poly: float


@dataclass
class TodayMatchRow:
    match_id: int
    home_name: str
    away_name: str
    kickoff_utc: datetime
    group_label: Optional[str]
    stage: str


@dataclass
class HomeContext:
    as_of: datetime
    competition_name: str
    days_to_kickoff: Optional[int]
    phase_label: str
    snapshot_ts: Optional[datetime]
    contenders: list[TopContenderRow]
    today_matches: list[TodayMatchRow]


async def _build_home_context() -> HomeContext:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()
        if comp is None:
            return HomeContext(
                as_of=now,
                competition_name="(unseeded)",
                days_to_kickoff=None,
                phase_label="not-seeded",
                snapshot_ts=None,
                contenders=[],
                today_matches=[],
            )

        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        contenders: list[TopContenderRow] = []
        if snap is not None:
            forecasts = (await session.execute(
                select(TournamentForecast)
                .where(TournamentForecast.snapshot_id == snap.id)
                .order_by(TournamentForecast.p_champion.desc())
                .limit(5)
            )).scalars().all()
            team_by_id = {
                t.id: t for t in (await session.execute(select(Team))).scalars().all()
            }
            for i, f in enumerate(forecasts, 1):
                contenders.append(TopContenderRow(
                    rank=i,
                    team_name=team_by_id[f.team_id].name if f.team_id in team_by_id else f"team-{f.team_id}",
                    p_champion=f.p_champion,
                    poly_p_champion=f.poly_p_champion or 0.0,
                    edge_vs_poly=f.edge_vs_poly,
                ))

        upcoming = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .where(Match.status == "SCHEDULED")
            .where(Match.kickoff_utc >= now)
            .order_by(Match.kickoff_utc.asc())
            .limit(20)
        )).scalars().all()
        teams_by_id = {
            t.id: t for t in (await session.execute(select(Team))).scalars().all()
        }
        today_matches: list[TodayMatchRow] = []
        for m in upcoming:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            today_matches.append(TodayMatchRow(
                match_id=m.id,
                home_name=teams_by_id[m.home_team_id].name,
                away_name=teams_by_id[m.away_team_id].name,
                kickoff_utc=m.kickoff_utc,
                group_label=m.group_label,
                stage=m.stage,
            ))
            if len(today_matches) >= 3:
                break

        # Compute phase
        def _naive(d: datetime) -> datetime:
            if d.tzinfo is None:
                return d
            return d.astimezone(timezone.utc).replace(tzinfo=None)
        a = _naive(now); s = _naive(comp.start_date); e = _naive(comp.end_date)
        if a < s:
            days_to = (s - a).days
            phase = f"T−{days_to} days · pre-tournament"
        elif a <= e:
            days_to = 0
            phase = "in-tournament"
        else:
            days_to = None
            phase = "post-tournament"

        return HomeContext(
            as_of=now,
            competition_name=comp.name,
            days_to_kickoff=days_to,
            phase_label=phase,
            snapshot_ts=snap.snapshot_date if snap else None,
            contenders=contenders,
            today_matches=today_matches,
        )


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    ctx = await _build_home_context()
    contenders_list = [
        {
            "rank": c.rank,
            "team_name": c.team_name,
            "p_champion": c.p_champion,
            "poly_p_champion": c.poly_p_champion,
            "edge_vs_poly": c.edge_vs_poly,
        }
        for c in ctx.contenders
    ]
    today_matches_list = [
        {
            "match_id": m.match_id,
            "home_name": m.home_name,
            "away_name": m.away_name,
            "kickoff_utc": m.kickoff_utc,
            "group_label": m.group_label,
            "stage": m.stage,
        }
        for m in ctx.today_matches
    ]
    context = {
        "as_of": ctx.as_of,
        "competition_name": ctx.competition_name,
        "days_to_kickoff": ctx.days_to_kickoff,
        "phase_label": ctx.phase_label,
        "snapshot_ts": ctx.snapshot_ts,
        "contenders": contenders_list,
        "today_matches": today_matches_list,
    }
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="home.html",
        context=context,
    )


@dataclass
class TournamentRow:
    rank: int
    team_name: str
    p_champion: float
    p_runner_up: float
    p_semi: float
    p_top_group: float
    poly_p_champion: float
    edge_vs_poly: float


_ALLOWED_SORT_KEYS = {
    "p_champion",
    "p_runner_up",
    "p_semi",
    "p_top_group",
    "edge_vs_poly",
}


@router.get("/tournament", response_class=HTMLResponse)
async def tournament(request: Request, order_by: str = "p_champion"):
    if order_by not in _ALLOWED_SORT_KEYS:
        order_by = "p_champion"

    settings = get_settings()
    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()
        if comp is None:
            context = {
                "request": request,
                "rows": [],
                "order_by": order_by,
                "competition_name": "(unseeded)",
            }
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="tournament.html",
                context=context,
            )

        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        if snap is None:
            context = {
                "request": request,
                "rows": [],
                "order_by": order_by,
                "competition_name": comp.name,
            }
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="tournament.html",
                context=context,
            )

        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
        teams_by_id = {t.id: t for t in (await session.execute(select(Team))).scalars().all()}

        # Sort in Python (small N) so we can sort by edge_vs_poly easily
        getter = {
            "p_champion": lambda f: f.p_champion,
            "p_runner_up": lambda f: f.p_runner_up,
            "p_semi": lambda f: f.p_semi,
            "p_top_group": lambda f: f.p_top_group,
            "edge_vs_poly": lambda f: f.edge_vs_poly,
        }[order_by]
        sorted_fcs = sorted(forecasts, key=getter, reverse=True)
        rows = [
            TournamentRow(
                rank=i,
                team_name=teams_by_id[f.team_id].name if f.team_id in teams_by_id else f"team-{f.team_id}",
                p_champion=f.p_champion,
                p_runner_up=f.p_runner_up,
                p_semi=f.p_semi,
                p_top_group=f.p_top_group,
                poly_p_champion=f.poly_p_champion or 0.0,
                edge_vs_poly=f.edge_vs_poly,
            )
            for i, f in enumerate(sorted_fcs, 1)
        ]

        context = {
            "request": request,
            "rows": [row.__dict__ for row in rows],
            "order_by": order_by,
            "competition_name": comp.name,
        }
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="tournament.html",
            context=context,
        )


@dataclass
class MatchDetailContext:
    match_id: int
    home_name: str
    away_name: str
    kickoff_utc: datetime
    stage: str
    group_label: Optional[str]
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    p_home: Optional[float]
    p_draw: Optional[float]
    p_away: Optional[float]
    p_home_poly: Optional[float]
    p_draw_poly: Optional[float]
    p_away_poly: Optional[float]
    edge_vs_poly: Optional[float]
    rationale_md: Optional[str]
    home_headlines: list[str]
    away_headlines: list[str]


@router.get("/match/{match_id}", response_class=HTMLResponse)
async def match_detail(request: Request, match_id: int):
    settings = get_settings()
    async with get_session() as session:
        match = (await session.execute(
            select(Match).where(Match.id == match_id)
        )).scalar_one_or_none()
        if match is None:
            raise HTTPException(status_code=404, detail="match not found")

        teams_by_id = {t.id: t for t in (await session.execute(select(Team))).scalars().all()}
        home = teams_by_id.get(match.home_team_id) if match.home_team_id else None
        away = teams_by_id.get(match.away_team_id) if match.away_team_id else None
        home_name = home.name if home else "TBD"
        away_name = away.name if away else "TBD"

        # Latest forecast for this match
        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == match.competition_id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        mf = None
        if snap is not None:
            mf = (await session.execute(
                select(MatchForecast)
                .where(MatchForecast.snapshot_id == snap.id)
                .where(MatchForecast.match_id == match.id)
            )).scalar_one_or_none()

        home_headlines: list[str] = []
        away_headlines: list[str] = []
        if home is not None:
            home_headlines = [
                n.title for n in (await session.execute(
                    select(NewsItem)
                    .where(NewsItem.team_id == home.id)
                    .order_by(NewsItem.ts.desc())
                    .limit(5)
                )).scalars().all()
            ]
        if away is not None:
            away_headlines = [
                n.title for n in (await session.execute(
                    select(NewsItem)
                    .where(NewsItem.team_id == away.id)
                    .order_by(NewsItem.ts.desc())
                    .limit(5)
                )).scalars().all()
            ]

        ctx = MatchDetailContext(
            match_id=match.id,
            home_name=home_name,
            away_name=away_name,
            kickoff_utc=match.kickoff_utc,
            stage=match.stage,
            group_label=match.group_label,
            status=match.status,
            home_score=match.home_score,
            away_score=match.away_score,
            p_home=mf.p_home if mf else None,
            p_draw=mf.p_draw if mf else None,
            p_away=mf.p_away if mf else None,
            p_home_poly=mf.p_home_poly if mf else None,
            p_draw_poly=mf.p_draw_poly if mf else None,
            p_away_poly=mf.p_away_poly if mf else None,
            edge_vs_poly=mf.edge_vs_poly if mf else None,
            rationale_md=mf.rationale_md if mf else None,
            home_headlines=home_headlines,
            away_headlines=away_headlines,
        )

    context = {
        "match_id": ctx.match_id,
        "home_name": ctx.home_name,
        "away_name": ctx.away_name,
        "kickoff_utc": ctx.kickoff_utc,
        "stage": ctx.stage,
        "group_label": ctx.group_label,
        "status": ctx.status,
        "home_score": ctx.home_score,
        "away_score": ctx.away_score,
        "p_home": ctx.p_home,
        "p_draw": ctx.p_draw,
        "p_away": ctx.p_away,
        "p_home_poly": ctx.p_home_poly,
        "p_draw_poly": ctx.p_draw_poly,
        "p_away_poly": ctx.p_away_poly,
        "edge_vs_poly": ctx.edge_vs_poly,
        "rationale_md": ctx.rationale_md,
        "home_headlines": ctx.home_headlines,
        "away_headlines": ctx.away_headlines,
    }
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="match_detail.html",
        context=context,
    )
