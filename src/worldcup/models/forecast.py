from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ForecastSnapshot(SQLModel, table=True):
    __tablename__ = "forecast_snapshot"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    snapshot_date: datetime
    snapshot_trigger: str  # daily | post_match | manual
    poly_odds_hash: str
    model_state_hash: Optional[str] = None
    model_version: str = "naive-poly-only-v0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TournamentForecast(SQLModel, table=True):
    __tablename__ = "tournament_forecast"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="forecast_snapshot.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    p_champion: float
    p_runner_up: float = 0.0
    p_semi: float = 0.0
    p_top_group: float = 0.0
    poly_p_champion: Optional[float] = None
    edge_vs_poly: float = 0.0


class MatchForecast(SQLModel, table=True):
    __tablename__ = "match_forecast"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="forecast_snapshot.id", index=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    p_home: float
    p_draw: float
    p_away: float
    p_home_poly: Optional[float] = None
    p_draw_poly: Optional[float] = None
    p_away_poly: Optional[float] = None
    edge_vs_poly: float = 0.0
    model_version: str = "elo-v0"
    rationale_md: Optional[str] = None
    predicted_score: Optional[str] = None       # e.g. "1-0"
    predicted_score_prob: Optional[float] = None # probability of that score
    expected_goals: Optional[float] = None       # expected total goals


class TopScorerForecast(SQLModel, table=True):
    __tablename__ = "top_scorer_forecast"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="forecast_snapshot.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    p_golden_boot: float
    expected_goals: float
    poly_p_top_scorer: Optional[float] = None
    edge_vs_poly: float = 0.0
    model_version: str = "top-scorer-v0"
