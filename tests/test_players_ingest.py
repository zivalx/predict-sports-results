from pathlib import Path

import pytest
from sqlmodel import select

from worldcup.db import get_session, init_db
from worldcup.ingest.players import load_seed_players
from worldcup.models import Player, Team
from scripts.seed_competition import seed


@pytest.fixture
def seed_csv(tmp_path: Path) -> Path:
    p = tmp_path / "players.csv"
    p.write_text(
        "player_name,country_code,position,goals_per_90\n"
        "Kylian Mbappe,FRA,FW,0.89\n"
        "Harry Kane,ENG,FW,0.81\n"
        "Erling Haaland,NOR,FW,1.05\n"  # No Norway team in DB → skipped
    )
    return p


@pytest.mark.asyncio
async def test_load_seed_players_inserts_matched_teams(seed_csv):
    await init_db()
    await seed()
    async with get_session() as session:
        session.add_all([
            Team(external_id=760, name="France", country_code="FRA"),
            Team(external_id=761, name="England", country_code="ENG"),
        ])
        await session.commit()

    summary = await load_seed_players(path=seed_csv)
    assert summary["inserted"] == 2
    assert summary["skipped_no_team"] == 1  # Norway not in DB

    async with get_session() as session:
        players = (await session.execute(select(Player))).scalars().all()
    assert len(players) == 2
    names = {p.name for p in players}
    assert names == {"Kylian Mbappe", "Harry Kane"}
    mbappe = next(p for p in players if p.name == "Kylian Mbappe")
    assert mbappe.goals_per_90 == 0.89
    assert mbappe.is_watchlist is True


@pytest.mark.asyncio
async def test_load_seed_players_is_idempotent(seed_csv):
    await init_db()
    await seed()
    async with get_session() as session:
        session.add(Team(external_id=760, name="France", country_code="FRA"))
        await session.commit()

    s1 = await load_seed_players(path=seed_csv)
    s2 = await load_seed_players(path=seed_csv)
    assert s1["inserted"] == 1
    assert s2["inserted"] == 0
    assert s2["skipped_existing"] == 1


@pytest.mark.asyncio
async def test_load_seed_players_handles_missing_file(tmp_path: Path):
    await init_db()
    await seed()

    summary = await load_seed_players(path=tmp_path / "does_not_exist.csv")
    assert summary == {"inserted": 0, "skipped_no_team": 0, "skipped_existing": 0}
