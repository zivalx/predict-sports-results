from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from worldcap.config import get_settings


def build_scheduler(refresh_fn: Callable) -> AsyncIOScheduler:
    """Build (but don't start) an AsyncIOScheduler with the daily refresh job registered.
    The caller starts/stops it via lifespan."""
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
    return scheduler
