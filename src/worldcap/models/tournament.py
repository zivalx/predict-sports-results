from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class TournamentFormat(SQLModel, table=True):
    __tablename__ = "tournament_format"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    groups_n: int
    group_size: int
    knockout_size: int  # number of teams entering the knockout stage
    tiebreaker_rules: list[str] = Field(sa_column=Column(JSON), default_factory=list)


class Competition(SQLModel, table=True):
    __tablename__ = "competition"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    code: str = Field(index=True, unique=True)  # e.g. "WC2026"
    format_id: int = Field(foreign_key="tournament_format.id")
    start_date: datetime
    end_date: datetime


class Team(SQLModel, table=True):
    __tablename__ = "team"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: int = Field(index=True, unique=True)  # football-data.org team id
    name: str
    country_code: Optional[str] = None
    fifa_rank: Optional[int] = None

    def __hash__(self) -> int:
        """Hash by ID if available, otherwise by external_id."""
        return hash(self.id if self.id is not None else self.external_id)

    def __eq__(self, other) -> bool:
        """Equality by ID if available, otherwise by external_id."""
        if not isinstance(other, Team):
            return False
        if self.id is not None and other.id is not None:
            return self.id == other.id
        return self.external_id == other.external_id


class Match(SQLModel, table=True):
    __tablename__ = "match"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: int = Field(index=True, unique=True)  # football-data.org match id
    competition_id: int = Field(foreign_key="competition.id")
    stage: str  # group | R32 | R16 | QF | SF | F | 3rd
    group_label: Optional[str] = None  # "A".."L" for WC26
    home_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    away_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    kickoff_utc: datetime
    status: str = "SCHEDULED"  # SCHEDULED | LIVE | FT | POSTPONED
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    bracket_slot: Optional[str] = None  # e.g. "R32-1", "QF-3", "F"; None for group stage
