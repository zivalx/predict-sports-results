import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from worldcup.config import get_settings
from worldcup.jobs.scheduler import build_scheduler


def test_build_scheduler_registers_daily_only_by_default(monkeypatch):
    monkeypatch.setenv("DAILY_REFRESH_CRON", "30 9 * * *")
    get_settings.cache_clear()

    async def fake_refresh():
        pass

    scheduler: AsyncIOScheduler = build_scheduler(refresh_fn=fake_refresh)

    jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
    # Daily-only mode — no post-match interval job unless post_match_fn is passed.
    assert set(jobs_by_id.keys()) == {"daily_refresh"}

    daily = jobs_by_id["daily_refresh"]
    assert str(daily.trigger).startswith("cron")
    fields = {f.name: str(f) for f in daily.trigger.fields}
    assert fields["minute"] == "30"
    assert fields["hour"] == "9"


def test_build_scheduler_accepts_custom_post_match_callable(monkeypatch):
    get_settings.cache_clear()

    async def fake_refresh():
        pass

    async def fake_post_match():
        pass

    scheduler = build_scheduler(refresh_fn=fake_refresh, post_match_fn=fake_post_match)
    jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
    assert jobs_by_id["post_match_check"].func is fake_post_match
    assert jobs_by_id["daily_refresh"].func is fake_refresh
