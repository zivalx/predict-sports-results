from typing import Optional

from sqlmodel import Field, SQLModel


class Player(SQLModel, table=True):
    __tablename__ = "player"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: Optional[int] = Field(default=None, index=True)  # nullable: CSV seed has no API id
    name: str
    team_id: int = Field(foreign_key="team.id", index=True)
    position: Optional[str] = None
    goals_per_90: float = 0.3
    is_watchlist: bool = True
