from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class MatchEvent(SQLModel, table=True):
    __tablename__ = "match_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    minute: Optional[int] = None
    type: str  # goal | own_goal | assist | red_card | yellow_card
    player_external_id: Optional[int] = Field(default=None, index=True)
    detail: dict = Field(sa_column=Column(JSON), default_factory=dict)


class TeamRating(SQLModel, table=True):
    __tablename__ = "team_rating"

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True, unique=True)
    rating: float = 1500.0
    last_updated: datetime
    source: str = "seed"  # seed | in_tournament
