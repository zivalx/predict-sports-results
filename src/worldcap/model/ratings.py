"""Load and persist team Elo ratings.

The seed CSV at data/fifa_ratings_seed.csv provides initial ratings keyed by
country_code (TLA, matching Team.country_code from the sports-data API).
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import select

from worldcap.db import get_session
from worldcap.log import get_logger
from worldcap.model.elo import INITIAL_RATING
from worldcap.models import Team, TeamRating


SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "fifa_ratings_seed.csv"

log = get_logger(__name__)


def _read_seed_csv(path: Path = SEED_PATH) -> dict[str, float]:
    """Return {country_code: rating} from the seed file."""
    out: dict[str, float] = {}
    if not path.exists():
        return out
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("country_code") or "").strip().upper()
            try:
                rating = float(row.get("rating", "").strip())
            except (TypeError, ValueError):
                continue
            if code:
                out[code] = rating
    return out


async def load_seed_ratings(path: Path = SEED_PATH) -> dict[str, int]:
    """Upsert TeamRating rows for every Team currently in the DB.

    Teams whose country_code is missing from the seed file get INITIAL_RATING.
    Teams whose TeamRating row already exists are left alone (so manual edits
    survive a reseed). Returns a summary dict.
    """
    seed = _read_seed_csv(path)
    inserted = 0
    skipped_existing = 0
    defaulted = 0

    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        existing_team_ids = {
            r.team_id for r in (await session.execute(select(TeamRating))).scalars().all()
        }

        for t in teams:
            if t.id in existing_team_ids:
                skipped_existing += 1
                continue
            code = (t.country_code or "").upper()
            if code in seed:
                rating = seed[code]
            else:
                rating = INITIAL_RATING
                defaulted += 1
            session.add(TeamRating(
                team_id=t.id,
                rating=rating,
                last_updated=datetime.now(timezone.utc),
                source="seed",
            ))
            inserted += 1

        await session.commit()

    log.info("ratings.seed", inserted=inserted, skipped_existing=skipped_existing, defaulted=defaulted)
    return {"inserted": inserted, "skipped_existing": skipped_existing, "defaulted": defaulted}
