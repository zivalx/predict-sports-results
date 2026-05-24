from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel


API_BASE = "https://api.football-data.org/v4"

_STAGE_MAP = {
    "GROUP_STAGE": "group",
    "LAST_32": "R32",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "FINAL": "F",
    "THIRD_PLACE": "3rd",
}

# football-data.org statuses → our canonical lifecycle.
# Source: https://docs.football-data.org/general/v4/lookup_tables.html
_STATUS_MAP = {
    "SCHEDULED": "SCHEDULED",   # scheduled but no specific kickoff time yet
    "TIMED": "SCHEDULED",       # scheduled with confirmed kickoff — still "upcoming" for us
    "IN_PLAY": "LIVE",
    "PAUSED": "LIVE",           # half-time / VAR pause
    "FINISHED": "FT",           # full time, result final
    "AWARDED": "FT",            # awarded result (e.g., walk-over)
    "SUSPENDED": "POSTPONED",
    "POSTPONED": "POSTPONED",
    "CANCELLED": "CANCELLED",
}


class TeamDTO(BaseModel):
    external_id: int
    name: str
    country_code: Optional[str] = None


class FixtureDTO(BaseModel):
    external_id: int
    stage: str
    group_label: Optional[str]
    kickoff_utc: datetime
    status: str
    home_external_id: Optional[int]
    away_external_id: Optional[int]
    home_score: Optional[int]
    away_score: Optional[int]


class FootballDataClient:
    def __init__(self, api_key: str, base_url: str = API_BASE, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Auth-Token": api_key} if api_key else {},
            timeout=timeout,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_teams(self, competition_code: str) -> list[TeamDTO]:
        r = await self._client.get(f"/competitions/{competition_code}/teams")
        r.raise_for_status()
        data = r.json()
        return [
            TeamDTO(
                external_id=t["id"],
                name=t["name"],
                country_code=t.get("tla"),
            )
            for t in data.get("teams", [])
        ]

    async def get_fixtures(self, competition_code: str) -> list[FixtureDTO]:
        r = await self._client.get(f"/competitions/{competition_code}/matches")
        r.raise_for_status()
        data = r.json()
        out: list[FixtureDTO] = []
        for m in data.get("matches", []):
            stage = _STAGE_MAP.get(m.get("stage", ""), m.get("stage", "").lower())
            group_raw = m.get("group")
            group_label = group_raw.removeprefix("GROUP_") if group_raw else None
            score = m.get("score", {}).get("fullTime", {})
            raw_status = m.get("status", "SCHEDULED")
            normalised_status = _STATUS_MAP.get(raw_status, raw_status)
            out.append(
                FixtureDTO(
                    external_id=m["id"],
                    stage=stage,
                    group_label=group_label,
                    kickoff_utc=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
                    status=normalised_status,
                    home_external_id=(m.get("homeTeam") or {}).get("id"),
                    away_external_id=(m.get("awayTeam") or {}).get("id"),
                    home_score=score.get("home"),
                    away_score=score.get("away"),
                )
            )
        return out
