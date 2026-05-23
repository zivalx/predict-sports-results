from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class NewsItem(SQLModel, table=True):
    __tablename__ = "news_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    match_id: Optional[int] = Field(default=None, foreign_key="match.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", index=True)
    source: str = "gnews"
    url: str = Field(index=True, unique=True)
    ts: datetime
    title: str
    summary: Optional[str] = None
    raw: dict = Field(sa_column=Column(JSON), default_factory=dict)


class SocialPost(SQLModel, table=True):
    __tablename__ = "social_post"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    match_id: Optional[int] = Field(default=None, foreign_key="match.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id", index=True)
    platform: str = "reddit"
    external_id: Optional[str] = None
    ts: datetime
    author: Optional[str] = None
    text: str
    engagement: Optional[int] = None
    url: str = Field(index=True, unique=True)


class SentimentScore(SQLModel, table=True):
    __tablename__ = "sentiment_score"

    id: Optional[int] = Field(default=None, primary_key=True)
    target_type: str = Field(index=True)  # "post" | "news_item" | "team" | "match"
    target_id: int = Field(index=True)
    ts: datetime
    score: float  # -1.0 .. 1.0
    confidence: float = 1.0
    model_version: str = "claude-haiku-4-5"
