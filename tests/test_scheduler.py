import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from worldcap.config import get_settings
from worldcap.jobs.scheduler import build_scheduler


def test_build_scheduler_registers_daily_job(monkeypatch):
    monkeypatch.setenv("DAILY_REFRESH_CRON", "30 9 * * *")
    get_settings.cache_clear()

    refresh_calls = []

    async def fake_refresh():
        refresh_calls.append("called")

    scheduler: AsyncIOScheduler = build_scheduler(refresh_fn=fake_refresh)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    trigger = jobs[0].trigger
    assert str(trigger).startswith("cron")
    fields = {f.name: str(f) for f in trigger.fields}
    assert fields["minute"] == "30"
    assert fields["hour"] == "9"
