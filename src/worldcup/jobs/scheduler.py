from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from worldcup.config import get_settings


def build_scheduler(
    refresh_fn: Callable,
    post_match_fn: Callable | None = None,
    post_match_interval_minutes: int = 5,
) -> AsyncIOScheduler:
    """Build (but don't start) an AsyncIOScheduler with the refresh jobs registered.

    - `refresh_fn`: called daily at the cron time in settings.
    - `post_match_fn`: if provided, called every `post_match_interval_minutes` minutes.
      When None (default), no post-match job is registered — daily-only mode.
    """
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        refresh_fn,
        trigger=CronTrigger.from_crontab(settings.daily_refresh_cron),
        id="daily_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if post_match_fn is not None:
        scheduler.add_job(
            post_match_fn,
            trigger=IntervalTrigger(minutes=post_match_interval_minutes),
            id="post_match_check",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    return scheduler
