"""HTML routes for the worldcup dashboard.

Server-rendered Jinja2 templates. HTMX is used for the manual-refresh button
via a partial swap. All data flows from the latest ForecastSnapshot.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.models import (
    Competition,
    ForecastSnapshot,
    Match,
    MatchForecast,
    NewsItem,
    Player,
    Team,
    TopScorerForecast,
    TournamentForecast,
)


@dataclass
class RetroResult:
    """Pre-match forecast vs actual outcome comparison."""
    icon: str          # "✓" or "✗"
    css_class: str     # "correct" or "wrong"
    text: str          # human-readable sentence


def _compute_retro(
    mf: MatchForecast,
    home_name: str,
    away_name: str,
    home_score: int,
    away_score: int,
) -> RetroResult:
    """Build a retro forecast comparison from a MatchForecast + final score."""
    # Predicted outcome
    probs = {"home_win": mf.p_home, "draw": mf.p_draw, "away_win": mf.p_away}
    predicted = max(probs, key=lambda k: probs[k])
    predicted_pct = round(probs[predicted] * 100)

    # Actual outcome
    if home_score > away_score:
        actual = "home_win"
    elif home_score == away_score:
        actual = "draw"
    else:
        actual = "away_win"

    # Build text
    if predicted == "home_win":
        predicted_label = f"{home_name} to win"
    elif predicted == "away_win":
        predicted_label = f"{away_name} to win"
    else:
        predicted_label = "a draw"

    score_str = f"{home_score}–{away_score}"

    if predicted == actual:
        return RetroResult(
            icon="✓",
            css_class="correct",
            text=f"We forecast {predicted_label} ({predicted_pct}%); correct — {home_name} {score_str} {away_name}",
        )
    else:
        if actual == "home_win":
            actual_label = f"{home_name} won"
        elif actual == "away_win":
            actual_label = f"{away_name} won"
        else:
            actual_label = "it finished a draw"
        return RetroResult(
            icon="✗",
            css_class="wrong",
            text=f"We forecast {predicted_label} ({predicted_pct}%); {actual_label} {score_str}",
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
    p_home: Optional[float] = None
    p_draw: Optional[float] = None
    p_away: Optional[float] = None
    edge_vs_poly: Optional[float] = None
    predicted_score: Optional[str] = None
    predicted_score_prob: Optional[float] = None
    expected_goals: Optional[float] = None
    p_home_poly: Optional[float] = None


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

        # Load match forecasts from latest snapshot
        mf_by_match: dict[int, MatchForecast] = {}
        if snap is not None:
            match_ids = [m.id for m in upcoming]
            if match_ids:
                mfs = (await session.execute(
                    select(MatchForecast)
                    .where(MatchForecast.snapshot_id == snap.id)
                    .where(MatchForecast.match_id.in_(match_ids))
                )).scalars().all()
                mf_by_match = {mf.match_id: mf for mf in mfs}

        today_matches: list[TodayMatchRow] = []
        for m in upcoming:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            mf = mf_by_match.get(m.id)
            today_matches.append(TodayMatchRow(
                match_id=m.id,
                home_name=teams_by_id[m.home_team_id].name,
                away_name=teams_by_id[m.away_team_id].name,
                kickoff_utc=m.kickoff_utc,
                group_label=m.group_label,
                stage=m.stage,
                p_home=mf.p_home if mf else None,
                p_draw=mf.p_draw if mf else None,
                p_away=mf.p_away if mf else None,
                edge_vs_poly=mf.edge_vs_poly if mf else None,
                predicted_score=mf.predicted_score if mf else None,
                predicted_score_prob=mf.predicted_score_prob if mf else None,
                expected_goals=mf.expected_goals if mf else None,
                p_home_poly=mf.p_home_poly if mf else None,
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
            "p_home": m.p_home,
            "p_draw": m.p_draw,
            "p_away": m.p_away,
            "edge_vs_poly": m.edge_vs_poly,
            "predicted_score": m.predicted_score,
            "predicted_score_prob": m.predicted_score_prob,
            "expected_goals": m.expected_goals,
            "p_home_poly": m.p_home_poly,
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
    predicted_score: Optional[str]
    predicted_score_prob: Optional[float]
    expected_goals: Optional[float]
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

        # Compute retro if match is FT and we have a forecast
        retro: Optional[RetroResult] = None
        if (
            match.status == "FT"
            and mf is not None
            and match.home_score is not None
            and match.away_score is not None
        ):
            retro = _compute_retro(mf, home_name, away_name, match.home_score, match.away_score)

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
            predicted_score=mf.predicted_score if mf else None,
            predicted_score_prob=mf.predicted_score_prob if mf else None,
            expected_goals=mf.expected_goals if mf else None,
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
        "predicted_score": ctx.predicted_score,
        "predicted_score_prob": ctx.predicted_score_prob,
        "expected_goals": ctx.expected_goals,
        "home_headlines": ctx.home_headlines,
        "away_headlines": ctx.away_headlines,
        "retro": retro,
    }
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="match_detail.html",
        context=context,
    )


@dataclass
class GoldenBootRow:
    rank: int
    player_name: str
    team_name: str
    p_golden_boot: float
    expected_goals: float
    poly_p_top_scorer: Optional[float]
    edge_vs_poly: float
    goals_per_90: float


@router.get("/golden-boot", response_class=HTMLResponse)
async def golden_boot(request: Request):
    settings = get_settings()
    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()
        if comp is None:
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="golden_boot.html",
                context={"request": request, "rows": [], "competition_name": "(unseeded)"},
            )

        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        if snap is None:
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="golden_boot.html",
                context={"request": request, "rows": [], "competition_name": comp.name},
            )

        rows_raw = (await session.execute(
            select(TopScorerForecast, Player, Team)
            .join(Player, TopScorerForecast.player_id == Player.id)
            .join(Team, Player.team_id == Team.id)
            .where(TopScorerForecast.snapshot_id == snap.id)
            .order_by(TopScorerForecast.p_golden_boot.desc())
        )).all()
        rows = [
            GoldenBootRow(
                rank=i,
                player_name=player.name,
                team_name=team.name,
                p_golden_boot=tsf.p_golden_boot,
                expected_goals=tsf.expected_goals,
                poly_p_top_scorer=tsf.poly_p_top_scorer,
                edge_vs_poly=tsf.edge_vs_poly,
                goals_per_90=player.goals_per_90,
            )
            for i, (tsf, player, team) in enumerate(rows_raw, 1)
        ]

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="golden_boot.html",
        context={"request": request, "rows": [row.__dict__ for row in rows], "competition_name": comp.name},
    )


@router.get("/bets", response_class=HTMLResponse)
async def bets(request: Request):
    settings = get_settings()
    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()
        if comp is None:
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="bets.html",
                context={
                    "competition_name": "(unseeded)",
                    "groups": [],
                    "bracket_rounds": [],
                    "total_group_matches": 0,
                    "total_knockout_matches": 0,
                    "total_with_forecast": 0,
                },
            )

        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        teams_by_id = {
            t.id: t for t in (await session.execute(select(Team))).scalars().all()
        }

        # All matches
        all_matches = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .order_by(Match.kickoff_utc.asc())
        )).scalars().all()

        # All match forecasts from latest snapshot
        mf_by_match: dict[int, MatchForecast] = {}
        if snap is not None:
            mfs = (await session.execute(
                select(MatchForecast).where(MatchForecast.snapshot_id == snap.id)
            )).scalars().all()
            mf_by_match = {mf.match_id: mf for mf in mfs}

        # Tournament forecasts for bracket projection
        tf_by_team: dict[int, TournamentForecast] = {}
        if snap is not None:
            tfs = (await session.execute(
                select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
            )).scalars().all()
            tf_by_team = {tf.team_id: tf for tf in tfs}

        def _rec_bet(mf: MatchForecast) -> tuple[str, str]:
            """Return (rec_key, rec_label) for the highest-probability outcome."""
            options = [
                ("home", mf.p_home, teams_by_id[mf_match_home].name if (mf_match_home := _match_home(mf.match_id)) else "Home"),
                ("draw", mf.p_draw, "Draw"),
                ("away", mf.p_away, teams_by_id[mf_match_away].name if (mf_match_away := _match_away(mf.match_id)) else "Away"),
            ]
            best = max(options, key=lambda x: x[1])
            return best[0], best[2]

        # Helper lookups
        match_by_id = {m.id: m for m in all_matches}

        def _match_home(mid: int) -> Optional[int]:
            return match_by_id[mid].home_team_id if mid in match_by_id else None

        def _match_away(mid: int) -> Optional[int]:
            return match_by_id[mid].away_team_id if mid in match_by_id else None

        def _build_match_row(m: Match) -> dict:
            mf = mf_by_match.get(m.id)
            home_name = teams_by_id[m.home_team_id].name if m.home_team_id and m.home_team_id in teams_by_id else "TBD"
            away_name = teams_by_id[m.away_team_id].name if m.away_team_id and m.away_team_id in teams_by_id else "TBD"
            rec = None
            rec_label = None
            if mf is not None:
                options = [
                    ("home", mf.p_home, home_name),
                    ("draw", mf.p_draw, "Draw"),
                    ("away", mf.p_away, away_name),
                ]
                best = max(options, key=lambda x: x[1])
                rec, rec_label = best[0], best[2]
            return {
                "match_id": m.id,
                "home_name": home_name,
                "away_name": away_name,
                "kickoff_utc": m.kickoff_utc,
                "status": m.status,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "p_home": mf.p_home if mf else None,
                "p_draw": mf.p_draw if mf else None,
                "p_away": mf.p_away if mf else None,
                "edge_vs_poly": mf.edge_vs_poly if mf else None,
                "rec": rec,
                "rec_label": rec_label,
            }

        # ── Group stage ──
        group_matches: dict[str, list[Match]] = {}
        knockout_matches: list[Match] = []
        for m in all_matches:
            if m.group_label:
                group_matches.setdefault(m.group_label, []).append(m)
            elif m.stage != "group":
                knockout_matches.append(m)

        groups = []
        for label in sorted(group_matches.keys()):
            matches = group_matches[label]
            rows = [_build_match_row(m) for m in matches]

            # Find projected group winner (highest p_top_group among teams in this group)
            team_ids_in_group = set()
            for m in matches:
                if m.home_team_id:
                    team_ids_in_group.add(m.home_team_id)
                if m.away_team_id:
                    team_ids_in_group.add(m.away_team_id)

            projected_winner = None
            projected_winner_pct = 0.0
            for tid in team_ids_in_group:
                tf = tf_by_team.get(tid)
                if tf and tf.p_top_group > projected_winner_pct:
                    projected_winner_pct = tf.p_top_group
                    projected_winner = teams_by_id[tid].name if tid in teams_by_id else None

            groups.append({
                "label": label,
                "matches": rows,
                "projected_winner": projected_winner,
                "projected_winner_pct": projected_winner_pct,
            })

        # ── Projected knockout bracket ──
        from worldcup.model.simulator.bracket_template import (
            WC2026_R32,
            WC2026_R16_FROM_R32,
            WC2026_QF_FROM_R16,
            WC2026_SF_FROM_QF,
            WC2026_F_FROM_SF,
        )

        # Build slot→team projection from group data
        # For each group, rank teams by p_top_group desc → project 1st, 2nd, 3rd, 4th
        slot_team: dict[str, tuple[str, float]] = {}  # slot → (team_name, confidence)
        for label in sorted(group_matches.keys()):
            team_ids_in_group = set()
            for m in group_matches[label]:
                if m.home_team_id:
                    team_ids_in_group.add(m.home_team_id)
                if m.away_team_id:
                    team_ids_in_group.add(m.away_team_id)

            # Sort by p_top_group descending
            ranked = sorted(
                team_ids_in_group,
                key=lambda tid: tf_by_team[tid].p_top_group if tid in tf_by_team else 0,
                reverse=True,
            )
            for pos, tid in enumerate(ranked):
                name = teams_by_id[tid].name if tid in teams_by_id else f"team-{tid}"
                tf = tf_by_team.get(tid)
                if pos == 0:
                    slot_team[f"{label}1"] = (name, tf.p_top_group if tf else 0)
                elif pos == 1:
                    # confidence of 2nd ≈ 1 - p_top_group (rough estimate)
                    slot_team[f"{label}2"] = (name, (1 - tf.p_top_group) if tf else 0)

        # Third-place projection: sort all projected 3rd-place teams
        all_thirds = []
        for label in sorted(group_matches.keys()):
            team_ids_in_group = set()
            for m in group_matches[label]:
                if m.home_team_id:
                    team_ids_in_group.add(m.home_team_id)
                if m.away_team_id:
                    team_ids_in_group.add(m.away_team_id)
            ranked = sorted(
                team_ids_in_group,
                key=lambda tid: tf_by_team[tid].p_top_group if tid in tf_by_team else 0,
                reverse=True,
            )
            if len(ranked) >= 3:
                tid = ranked[2]
                name = teams_by_id[tid].name if tid in teams_by_id else f"team-{tid}"
                tf = tf_by_team.get(tid)
                # Use p_semi as rough proxy for 3rd-place strength
                strength = tf.p_semi if tf else 0
                all_thirds.append((name, strength))
        all_thirds.sort(key=lambda x: x[1], reverse=True)
        for i, (name, strength) in enumerate(all_thirds[:8]):
            slot_team[f"3RD_{i + 1}"] = (name, strength)

        def _resolve_slot(slot: str) -> tuple[str, Optional[float]]:
            if slot in slot_team:
                return slot_team[slot]
            return (slot, None)

        # If a knockout match already has teams assigned in the DB, use those instead
        ko_match_by_slot: dict[str, Match] = {}
        for m in knockout_matches:
            if m.bracket_slot:
                ko_match_by_slot[m.bracket_slot] = m

        def _build_ko_match(idx: int, left_slot: str, right_slot: str, round_prefix: str) -> dict:
            slot_label = f"{round_prefix}-{idx + 1}"
            db_match = ko_match_by_slot.get(slot_label)

            if db_match and db_match.home_team_id and db_match.away_team_id:
                # Real match with teams assigned
                row = _build_match_row(db_match)
                row["home_conf"] = None
                row["away_conf"] = None
                return row

            # Projected
            home_name, home_conf = _resolve_slot(left_slot)
            away_name, away_conf = _resolve_slot(right_slot)
            return {
                "home_name": home_name,
                "away_name": away_name,
                "home_conf": home_conf,
                "away_conf": away_conf,
                "p_home": None,
                "p_draw": None,
                "p_away": None,
                "rec": None,
                "rec_label": None,
            }

        # Build R32
        r32_matches = [
            _build_ko_match(i, left, right, "R32")
            for i, (left, right) in enumerate(WC2026_R32)
        ]

        # For R16+, we'd need to project winners of previous rounds — just show slots
        def _winner_label(match_row: dict) -> str:
            """Pick the projected winner of a match for downstream bracket display."""
            if match_row.get("p_home") is not None and match_row.get("p_away") is not None:
                if match_row["p_home"] >= match_row["p_away"]:
                    return match_row["home_name"]
                return match_row["away_name"]
            # Fall back to home (higher-seeded) if no forecast
            return match_row["home_name"]

        r16_matches = []
        for i, (a, b) in enumerate(WC2026_R16_FROM_R32):
            home_name = _winner_label(r32_matches[a])
            away_name = _winner_label(r32_matches[b])
            slot_label = f"R16-{i + 1}"
            db_match = ko_match_by_slot.get(slot_label)
            if db_match and db_match.home_team_id and db_match.away_team_id:
                row = _build_match_row(db_match)
                row["home_conf"] = None
                row["away_conf"] = None
            else:
                row = {
                    "home_name": home_name, "away_name": away_name,
                    "home_conf": None, "away_conf": None,
                    "p_home": None, "p_draw": None, "p_away": None,
                    "rec": None, "rec_label": None,
                }
            r16_matches.append(row)

        qf_matches = []
        for i, (a, b) in enumerate(WC2026_QF_FROM_R16):
            home_name = _winner_label(r16_matches[a])
            away_name = _winner_label(r16_matches[b])
            slot_label = f"QF-{i + 1}"
            db_match = ko_match_by_slot.get(slot_label)
            if db_match and db_match.home_team_id and db_match.away_team_id:
                row = _build_match_row(db_match)
                row["home_conf"] = None
                row["away_conf"] = None
            else:
                row = {
                    "home_name": home_name, "away_name": away_name,
                    "home_conf": None, "away_conf": None,
                    "p_home": None, "p_draw": None, "p_away": None,
                    "rec": None, "rec_label": None,
                }
            qf_matches.append(row)

        sf_matches = []
        for i, (a, b) in enumerate(WC2026_SF_FROM_QF):
            home_name = _winner_label(qf_matches[a])
            away_name = _winner_label(qf_matches[b])
            slot_label = f"SF-{i + 1}"
            db_match = ko_match_by_slot.get(slot_label)
            if db_match and db_match.home_team_id and db_match.away_team_id:
                row = _build_match_row(db_match)
                row["home_conf"] = None
                row["away_conf"] = None
            else:
                row = {
                    "home_name": home_name, "away_name": away_name,
                    "home_conf": None, "away_conf": None,
                    "p_home": None, "p_draw": None, "p_away": None,
                    "rec": None, "rec_label": None,
                }
            sf_matches.append(row)

        a_sf, b_sf = WC2026_F_FROM_SF
        final_home = _winner_label(sf_matches[a_sf])
        final_away = _winner_label(sf_matches[b_sf])
        db_final = ko_match_by_slot.get("F")
        if db_final and db_final.home_team_id and db_final.away_team_id:
            final_row = _build_match_row(db_final)
            final_row["home_conf"] = None
            final_row["away_conf"] = None
        else:
            final_row = {
                "home_name": final_home, "away_name": final_away,
                "home_conf": None, "away_conf": None,
                "p_home": None, "p_draw": None, "p_away": None,
                "rec": None, "rec_label": None,
            }
        final_matches = [final_row]

        bracket_rounds = [
            {"name": "Round of 32", "matches": r32_matches, "has_forecasts": any(m.get("p_home") is not None for m in r32_matches)},
            {"name": "Round of 16", "matches": r16_matches, "has_forecasts": any(m.get("p_home") is not None for m in r16_matches)},
            {"name": "Quarter-finals", "matches": qf_matches, "has_forecasts": any(m.get("p_home") is not None for m in qf_matches)},
            {"name": "Semi-finals", "matches": sf_matches, "has_forecasts": any(m.get("p_home") is not None for m in sf_matches)},
            {"name": "Final", "matches": final_matches, "has_forecasts": any(m.get("p_home") is not None for m in final_matches)},
        ]

        total_group = sum(len(g["matches"]) for g in groups)
        total_ko = len(knockout_matches)
        total_forecast = len(mf_by_match)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="bets.html",
        context={
            "competition_name": comp.name,
            "groups": groups,
            "bracket_rounds": bracket_rounds,
            "total_group_matches": total_group,
            "total_knockout_matches": total_ko,
            "total_with_forecast": total_forecast,
        },
    )


@dataclass
class ResultMatchRow:
    match_id: int
    home_name: str
    away_name: str
    home_score: int
    away_score: int
    kickoff_utc: datetime
    group_label: Optional[str]
    stage: str
    retro: Optional[RetroResult]


@router.get("/results", response_class=HTMLResponse)
async def results(request: Request):
    settings = get_settings()
    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()

        competition_start: Optional[datetime] = comp.start_date if comp else None

        if comp is None:
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="results.html",
                context={"matches": [], "competition_start": None},
            )

        # All FT matches, newest first
        ft_matches = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .where(Match.status == "FT")
            .order_by(Match.kickoff_utc.desc())
        )).scalars().all()

        if not ft_matches:
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="results.html",
                context={"matches": [], "competition_start": competition_start},
            )

        teams_by_id = {
            t.id: t for t in (await session.execute(select(Team))).scalars().all()
        }

        # Latest snapshot for forecasts
        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        # Load all match forecasts for these matches from the latest snapshot
        mf_by_match_id: dict[int, MatchForecast] = {}
        if snap is not None:
            match_ids = [m.id for m in ft_matches]
            mfs = (await session.execute(
                select(MatchForecast)
                .where(MatchForecast.snapshot_id == snap.id)
                .where(MatchForecast.match_id.in_(match_ids))
            )).scalars().all()
            mf_by_match_id = {mf.match_id: mf for mf in mfs}

        rows: list[dict] = []
        for m in ft_matches:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            home_name = teams_by_id[m.home_team_id].name if m.home_team_id in teams_by_id else "TBD"
            away_name = teams_by_id[m.away_team_id].name if m.away_team_id in teams_by_id else "TBD"
            mf = mf_by_match_id.get(m.id)
            retro: Optional[RetroResult] = None
            if mf is not None and m.home_score is not None and m.away_score is not None:
                retro = _compute_retro(mf, home_name, away_name, m.home_score, m.away_score)
            rows.append({
                "match_id": m.id,
                "home_name": home_name,
                "away_name": away_name,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "kickoff_utc": m.kickoff_utc,
                "group_label": m.group_label,
                "stage": m.stage,
                "retro": retro,
            })

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="results.html",
        context={"matches": rows, "competition_start": competition_start},
    )


@router.get("/matches", response_class=HTMLResponse)
async def matches(request: Request):
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == settings.db_competition_code)
        )).scalar_one_or_none()
        if comp is None:
            return request.app.state.templates.TemplateResponse(
                request=request, name="matches.html",
                context={"days": [], "competition_name": "(unseeded)"},
            )

        snap = (await session.execute(
            select(ForecastSnapshot)
            .where(ForecastSnapshot.competition_id == comp.id)
            .order_by(ForecastSnapshot.snapshot_date.desc())
        )).scalars().first()

        all_matches = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .where(Match.home_team_id.is_not(None))
            .where(Match.away_team_id.is_not(None))
            .order_by(Match.kickoff_utc.asc())
        )).scalars().all()

        teams_by_id = {
            t.id: t for t in (await session.execute(select(Team))).scalars().all()
        }

        mf_by_match: dict[int, MatchForecast] = {}
        if snap is not None:
            mfs = (await session.execute(
                select(MatchForecast).where(MatchForecast.snapshot_id == snap.id)
            )).scalars().all()
            mf_by_match = {mf.match_id: mf for mf in mfs}

        # Group by date
        from collections import OrderedDict
        days: OrderedDict[str, list] = OrderedDict()
        for m in all_matches:
            date_key = m.kickoff_utc.strftime("%A %-d %B")
            mf = mf_by_match.get(m.id)
            row = {
                "match_id": m.id,
                "home_name": teams_by_id[m.home_team_id].name,
                "away_name": teams_by_id[m.away_team_id].name,
                "kickoff_utc": m.kickoff_utc,
                "group_label": m.group_label,
                "stage": m.stage,
                "status": m.status,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "p_home": mf.p_home if mf else None,
                "p_draw": mf.p_draw if mf else None,
                "p_away": mf.p_away if mf else None,
                "predicted_score": mf.predicted_score if mf else None,
                "predicted_score_prob": mf.predicted_score_prob if mf else None,
                "expected_goals": mf.expected_goals if mf else None,
                "edge_vs_poly": mf.edge_vs_poly if mf else None,
                "p_home_poly": mf.p_home_poly if mf else None,
            }
            days.setdefault(date_key, []).append(row)

    return request.app.state.templates.TemplateResponse(
        request=request, name="matches.html",
        context={"days": dict(days), "competition_name": comp.name},
    )


@router.get("/status", response_class=HTMLResponse)
async def status(request: Request):
    from worldcup.jobs import refresh as refresh_mod
    rr = refresh_mod.last_refresh_result
    refresh_data = rr.to_dict() if rr else None
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="status.html",
        context={"refresh": refresh_data},
    )
