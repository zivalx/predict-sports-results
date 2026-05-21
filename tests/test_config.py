from worldcap.config import get_settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "abc123")
    monkeypatch.setenv("DAILY_REFRESH_CRON", "30 8 * * *")
    get_settings.cache_clear()
    s = get_settings()
    assert s.football_data_api_key == "abc123"
    assert s.daily_refresh_cron == "30 8 * * *"
    assert s.database_url.startswith("sqlite+aiosqlite://")


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DAILY_REFRESH_CRON", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.daily_refresh_cron == "0 9 * * *"
