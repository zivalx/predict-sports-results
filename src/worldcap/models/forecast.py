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
