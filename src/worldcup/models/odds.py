from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class OddsSnapshot(SQLModel, table=True):
    __tablename__ = "odds_snapshot"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    match_id: Optional[int] = Field(default=None, foreign_key="match.id", index=True)
    market_type: str  # match_3way | outright_winner | stage_advancement | top_scorer
    source: str = "polymarket"
    ts: datetime
    outcomes: dict = Field(sa_column=Column(JSON))
    volume: Optional[float] = None
