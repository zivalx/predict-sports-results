import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from worldcap.config import get_settings
from worldcap.jobs.scheduler import build_scheduler


def test_build_scheduler_registers_daily_and_post_match_jobs(monkeypatch):
    monkeypatch.setenv("DAILY_REFRESH_CRON", "30 9 * * *")
    get_settings.cache_clear()

    async def fake_refresh():
        pass

    scheduler: AsyncIOScheduler = build_scheduler(refresh_fn=fake_refresh)

    jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs_by_id.keys()) == {"daily_refresh", "post_match_check"}

    # Daily job: cron trigger with the configured fields.
    daily = jobs_by_id["daily_refresh"]
    assert str(daily.trigger).startswith("cron")
    fields = {f.name: str(f) for f in daily.trigger.fields}
    assert fields["minute"] == "30"
    assert fields["hour"] == "9"

    # Post-match job: interval trigger at the default 5 minutes.
    post = jobs_by_id["post_match_check"]
    assert "interval" in str(post.trigger)


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
