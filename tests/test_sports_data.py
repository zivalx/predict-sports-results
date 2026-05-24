import httpx
import pytest
import respx

from worldcup.ingest.sports_data import (
    FootballDataClient,
    TeamDTO,
    FixtureDTO,
)


@pytest.mark.asyncio
async def test_get_teams(respx_mock: respx.MockRouter):
    respx_mock.get("https://api.football-data.org/v4/competitions/WC/teams").mock(
        return_value=httpx.Response(
            200,
            json={
                "teams": [
                    {"id": 759, "name": "Brazil", "tla": "BRA"},
                    {"id": 760, "name": "France", "tla": "FRA"},
                ]
            },
        )
    )
    client = FootballDataClient(api_key="k")
    teams = await client.get_teams("WC")
    assert teams == [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]


@pytest.mark.asyncio
async def test_get_fixtures(respx_mock: respx.MockRouter):
    respx_mock.get("https://api.football-data.org/v4/competitions/WC/matches").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 1,
                        "stage": "GROUP_STAGE",
                        "group": "GROUP_A",
                        "utcDate": "2026-06-11T20:00:00Z",
                        "status": "SCHEDULED",
                        "homeTeam": {"id": 759},
                        "awayTeam": {"id": 760},
                        "score": {"fullTime": {"home": None, "away": None}},
                    }
                ]
            },
        )
    )
    client = FootballDataClient(api_key="k")
    fixtures = await client.get_fixtures("WC")
    assert len(fixtures) == 1
    f = fixtures[0]
    assert f.external_id == 1
    assert f.stage == "group"
    assert f.group_label == "A"
    assert f.home_external_id == 759
    assert f.away_external_id == 760
    assert f.status == "SCHEDULED"
