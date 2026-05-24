"""JSON endpoints designed for MCP agent consumption.

Docstrings here become the MCP tool descriptions — keep them concrete and
agent-friendly. Pydantic response models give strict schemas.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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
    SentimentScore,
    Team,
    TeamRating,
    TopScorerForecast,
    TournamentForecast,
)


mcp_router = APIRouter(prefix="/api", tags=["mcp"])


class TournamentOutlookEntry(BaseModel):
    team: str
    p_champion: float
    p_runner_up: float
    p_semi: float
    p_top_group: float
    poly_p_champion: Optional[float]
    edge_vs_poly: float


class TournamentOutlookResponse(BaseModel):
    snapshot_date: Optional[str]
    entries: list[TournamentOutlookEntry]


class MatchForecastResponse(BaseModel):
    home_team: str
    away_team: str
    kickoff_utc: str
    stage: str
    status: str
    p_home: Optional[float]
    p_draw: Optional[float]
    p_away: Optional[float]
    poly_p_home: Optional[float]
    poly_p_draw: Optional[float]
    poly_p_away: Optional[float]
    edge_vs_poly: Optional[float]
    rationale_md: Optional[str]
    home_recent_headlines: list[str]
    away_recent_headlines: list[str]


class GoldenBootEntry(BaseModel):
    player: str
    team: str
    p_golden_boot: float
    expected_goals: float
    poly_p_top_scorer: Optional[float]
    edge_vs_poly: float
    goals_per_90: float


class GoldenBootResponse(BaseModel):
    snapshot_date: Optional[str]
    entries: list[GoldenBootEntry]


class TeamOverviewResponse(BaseModel):
    team: str
    elo_rating: Optional[float]
    p_champion: Optional[float]
    p_semi: Optional[float]
    p_top_group: Optional[float]
    sentiment: Optional[float]
    recent_headlines: list[str]
    upcoming_matches: list[str]


async def _latest_snapshot_id(session) -> tuple[Optional[int], Optional[str]]:
    settings = get_settings()
    comp = (await session.execute(
        select(Competition).where(Competition.code == settings.db_competition_code)
    )).scalar_one_or_none()
    if comp is None:
        return None, None
    snap = (await session.execute(
        select(ForecastSnapshot)
        .where(ForecastSnapshot.competition_id == comp.id)
        .order_by(ForecastSnapshot.snapshot_date.desc())
    )).scalars().first()
    if snap is None:
        return None, None
    return snap.id, snap.snapshot_date.isoformat()


@mcp_router.get("/tournament_outlook", response_model=TournamentOutlookResponse, operation_id="get_tournament_outlook")
async def get_tournament_outlook(top_n: int = 10) -> TournamentOutlookResponse:
    """Return the top-N tournament-level forecast entries from the latest snapshot.

    Each entry includes per-team probabilities of winning the cup, being
    runner-up, reaching the semifinal, topping their group, plus the
    Polymarket implied probability (when available) and the edge our model
    has vs the market.
    """
    async with get_session() as session:
        snap_id, snap_date = await _latest_snapshot_id(session)
        if snap_id is None:
            return TournamentOutlookResponse(snapshot_date=None, entries=[])
        forecasts = (await session.execute(
            select(TournamentForecast)
            .where(TournamentForecast.snapshot_id == snap_id)
            .order_by(TournamentForecast.p_champion.desc())
            .limit(top_n)
        )).scalars().all()
        teams_by_id = {t.id: t for t in (await session.execute(select(Team))).scalars().all()}
        entries = [
            TournamentOutlookEntry(
                team=teams_by_id[f.team_id].name if f.team_id in teams_by_id else f"team-{f.team_id}",
                p_champion=f.p_champion,
                p_runner_up=f.p_runner_up,
                p_semi=f.p_semi,
                p_top_group=f.p_top_group,
                poly_p_champion=f.poly_p_champion,
                edge_vs_poly=f.edge_vs_poly,
            )
            for f in forecasts
        ]
        return TournamentOutlookResponse(snapshot_date=snap_date, entries=entries)


@mcp_router.get("/match_forecast", response_model=MatchForecastResponse, operation_id="get_match_forecast")
async def get_match_forecast(home_team: str, away_team: str) -> MatchForecastResponse:
    """Look up the forecast for an upcoming or completed match by team names.

    Team names are matched case-insensitively against `Team.name`. Returns
    the most recent forecast snapshot's row for that match, with our 3-way
    probability, Polymarket odds (when available), the rationale paragraph,
    and the top 5 recent news headlines per team.
    """
    home_team_l = home_team.strip().lower()
    away_team_l = away_team.strip().lower()
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        teams_by_name = {t.name.lower(): t for t in teams}
        home = teams_by_name.get(home_team_l)
        away = teams_by_name.get(away_team_l)
        if home is None or away is None:
            raise HTTPException(status_code=404, detail=f"team(s) not found: {home_team}, {away_team}")

        match = (await session.execute(
            select(Match)
            .where(Match.home_team_id == home.id)
            .where(Match.away_team_id == away.id)
            .order_by(Match.kickoff_utc.asc())
        )).scalars().first()
        if match is None:
            raise HTTPException(status_code=404, detail=f"match not found: {home_team} vs {away_team}")

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

        home_headlines = [
            n.title for n in (await session.execute(
                select(NewsItem)
                .where(NewsItem.team_id == home.id)
                .order_by(NewsItem.ts.desc())
                .limit(5)
            )).scalars().all()
        ]
        away_headlines = [
            n.title for n in (await session.execute(
                select(NewsItem)
                .where(NewsItem.team_id == away.id)
                .order_by(NewsItem.ts.desc())
                .limit(5)
            )).scalars().all()
        ]

        return MatchForecastResponse(
            home_team=home.name,
            away_team=away.name,
            kickoff_utc=match.kickoff_utc.isoformat(),
            stage=match.stage,
            status=match.status,
            p_home=mf.p_home if mf else None,
            p_draw=mf.p_draw if mf else None,
            p_away=mf.p_away if mf else None,
            poly_p_home=mf.p_home_poly if mf else None,
            poly_p_draw=mf.p_draw_poly if mf else None,
            poly_p_away=mf.p_away_poly if mf else None,
            edge_vs_poly=mf.edge_vs_poly if mf else None,
            rationale_md=mf.rationale_md if mf else None,
            home_recent_headlines=home_headlines,
            away_recent_headlines=away_headlines,
        )


@mcp_router.get("/golden_boot_race", response_model=GoldenBootResponse, operation_id="get_golden_boot_race")
async def get_golden_boot_race(top_n: int = 10) -> GoldenBootResponse:
    """Return the top-N Golden Boot contenders from the latest snapshot.

    Each entry includes the player, their team, our model's probability they
    finish the tournament as top scorer, the model's expected total goals,
    Polymarket's implied probability (when available), the edge, and the
    player's goals-per-90 prior.
    """
    async with get_session() as session:
        snap_id, snap_date = await _latest_snapshot_id(session)
        if snap_id is None:
            return GoldenBootResponse(snapshot_date=None, entries=[])
        rows_raw = (await session.execute(
            select(TopScorerForecast, Player, Team)
            .join(Player, TopScorerForecast.player_id == Player.id)
            .join(Team, Player.team_id == Team.id)
            .where(TopScorerForecast.snapshot_id == snap_id)
            .order_by(TopScorerForecast.p_golden_boot.desc())
            .limit(top_n)
        )).all()
        entries = [
            GoldenBootEntry(
                player=player.name,
                team=team.name,
                p_golden_boot=tsf.p_golden_boot,
                expected_goals=tsf.expected_goals,
                poly_p_top_scorer=tsf.poly_p_top_scorer,
                edge_vs_poly=tsf.edge_vs_poly,
                goals_per_90=player.goals_per_90,
            )
            for tsf, player, team in rows_raw
        ]
        return GoldenBootResponse(snapshot_date=snap_date, entries=entries)


@mcp_router.get("/team_overview", response_model=TeamOverviewResponse, operation_id="get_team_overview")
async def get_team_overview(team_name: str) -> TeamOverviewResponse:
    """Return a per-team overview: Elo rating, tournament-level probabilities,
    aggregated sentiment, recent news headlines, and upcoming match cards.

    Team name is matched case-insensitively. 404 if the team isn't in the DB.
    """
    name_l = team_name.strip().lower()
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        team = next((t for t in teams if t.name.lower() == name_l), None)
        if team is None:
            raise HTTPException(status_code=404, detail=f"team not found: {team_name}")

        rating_row = (await session.execute(
            select(TeamRating).where(TeamRating.team_id == team.id)
        )).scalar_one_or_none()

        snap_id, _ = await _latest_snapshot_id(session)
        tf = None
        if snap_id is not None:
            tf = (await session.execute(
                select(TournamentForecast)
                .where(TournamentForecast.snapshot_id == snap_id)
                .where(TournamentForecast.team_id == team.id)
            )).scalar_one_or_none()

        sentiment_row = (await session.execute(
            select(SentimentScore)
            .where(SentimentScore.target_type == "team")
            .where(SentimentScore.target_id == team.id)
            .order_by(SentimentScore.ts.desc())
        )).scalars().first()

        headlines = [
            n.title for n in (await session.execute(
                select(NewsItem)
                .where(NewsItem.team_id == team.id)
                .order_by(NewsItem.ts.desc())
                .limit(5)
            )).scalars().all()
        ]

        upcoming = (await session.execute(
            select(Match)
            .where((Match.home_team_id == team.id) | (Match.away_team_id == team.id))
            .where(Match.status == "SCHEDULED")
            .order_by(Match.kickoff_utc.asc())
            .limit(3)
        )).scalars().all()
        teams_by_id = {t.id: t for t in teams}
        upcoming_strs = []
        for m in upcoming:
            h = teams_by_id.get(m.home_team_id)
            a = teams_by_id.get(m.away_team_id)
            if h is None or a is None:
                continue
            upcoming_strs.append(
                f"{h.name} vs {a.name} · {m.kickoff_utc.strftime('%Y-%m-%d %H:%M UTC')}"
            )

        return TeamOverviewResponse(
            team=team.name,
            elo_rating=rating_row.rating if rating_row else None,
            p_champion=tf.p_champion if tf else None,
            p_semi=tf.p_semi if tf else None,
            p_top_group=tf.p_top_group if tf else None,
            sentiment=sentiment_row.score if sentiment_row else None,
            recent_headlines=headlines,
            upcoming_matches=upcoming_strs,
        )
