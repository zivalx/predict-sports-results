from worldcup.config import get_settings


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


def test_settings_picks_up_p4_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-1")
    monkeypatch.setenv("GNEWS_API_KEY", "gn-1")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "rc-1")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "rs-1")
    monkeypatch.setenv("RATIONALE_TOKEN_BUDGET", "55000")
    monkeypatch.setenv("SENTIMENT_MODEL", "claude-haiku-x")
    monkeypatch.setenv("RATIONALE_MODEL", "claude-sonnet-x")
    get_settings.cache_clear()
    s = get_settings()
    assert s.anthropic_api_key == "ak-1"
    assert s.gnews_api_key == "gn-1"
    assert s.reddit_client_id == "rc-1"
    assert s.reddit_client_secret == "rs-1"
    assert s.rationale_token_budget == 55000
    assert s.sentiment_model == "claude-haiku-x"
    assert s.rationale_model == "claude-sonnet-x"
