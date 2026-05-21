# worldcap

World Cup 2026 pre-match forecast feed. See `docs/specs/2026-05-21-worldcap-design.md`.

## Quick start

    uv sync
    cp .env.example .env  # fill in FOOTBALL_DATA_API_KEY
    uv run alembic upgrade head
    uv run python scripts/seed_competition.py
    uv run uvicorn worldcap.api.app:app --reload
