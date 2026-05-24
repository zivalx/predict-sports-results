"""Load watchlist players from data/players_seed.csv into the Player table.

Idempotent upsert keyed by (Player.name, Player.team_id). Players whose
country_code can't be matched to a Team in the DB are skipped with a warning
(those teams haven't been ingested yet).
"""

import csv
from pathlib import Path

from sqlmodel import select

from worldcup.db import get_session
from worldcup.log import get_logger
from worldcup.models import Player, Team


SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "players_seed.csv"

log = get_logger(__name__)


def _read_seed_csv(path: Path = SEED_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("player_name") or "").strip()
            code = (row.get("country_code") or "").strip().upper()
            position = (row.get("position") or "").strip() or None
            try:
                g90 = float(row.get("goals_per_90") or 0.0)
            except (TypeError, ValueError):
                g90 = 0.0
            if not name or not code:
                continue
            rows.append({
                "name": name,
                "country_code": code,
                "position": position,
                "goals_per_90": g90,
            })
    return rows


async def load_seed_players(path: Path = SEED_PATH) -> dict[str, int]:
    """Upsert Player rows from the CSV. Returns a summary dict."""
    seed = _read_seed_csv(path)
    inserted = 0
    skipped_no_team = 0
    skipped_existing = 0

    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        team_by_code: dict[str, Team] = {(t.country_code or "").upper(): t for t in teams}
        existing = (await session.execute(select(Player))).scalars().all()
        existing_keys = {(p.name, p.team_id) for p in existing}

        for r in seed:
            team = team_by_code.get(r["country_code"])
            if team is None:
                skipped_no_team += 1
                continue
            key = (r["name"], team.id)
            if key in existing_keys:
                skipped_existing += 1
                continue
            session.add(Player(
                name=r["name"],
                team_id=team.id,
                position=r["position"],
                goals_per_90=r["goals_per_90"],
                is_watchlist=True,
            ))
            existing_keys.add(key)
            inserted += 1

        await session.commit()

    log.info(
        "players.seed",
        inserted=inserted,
        skipped_no_team=skipped_no_team,
        skipped_existing=skipped_existing,
    )
    return {
        "inserted": inserted,
        "skipped_no_team": skipped_no_team,
        "skipped_existing": skipped_existing,
    }
