"""Seed the WC 2026 competition row + tournament format. Idempotent."""

import asyncio
from datetime import datetime, timezone

from sqlmodel import select

from worldcup.config import get_settings
from worldcup.db import get_session
from worldcup.models import Competition, TournamentFormat


WC2026_FORMAT = TournamentFormat(
    name="World Cup 48 (12 groups of 4 + R32)",
    groups_n=12,
    group_size=4,
    knockout_size=32,
    tiebreaker_rules=[
        "points",
        "goal_difference",
        "goals_for",
        "head_to_head",
        "fair_play",
        "draw_of_lots",
    ],
)


async def seed() -> None:
    settings = get_settings()
    async with get_session() as session:
        existing = (await session.execute(select(Competition).where(Competition.code == settings.db_competition_code))).scalar_one_or_none()
        if existing:
            return

        fmt = TournamentFormat(**WC2026_FORMAT.model_dump(exclude={"id"}))
        session.add(fmt)
        await session.flush()

        comp = Competition(
            name="FIFA World Cup 2026",
            code=settings.db_competition_code,
            format_id=fmt.id,
            start_date=datetime(2026, 6, 11, tzinfo=timezone.utc),
            end_date=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )
        session.add(comp)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
