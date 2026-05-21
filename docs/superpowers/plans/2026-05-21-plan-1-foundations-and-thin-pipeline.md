# worldcap — Plan 1: Foundations + thin end-to-end pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the worldcap service end-to-end with the thinnest possible pipeline: ingest WC 2026 fixtures + Polymarket outright-winner odds, persist a `ForecastSnapshot` using Polymarket-as-forecast, render a Markdown digest in pre-tournament mode, expose a manual refresh endpoint, and run the pipeline daily via APScheduler.

**Architecture:** Single Python 3.12 process. FastAPI + APScheduler in one event loop. SQLModel over async SQLite (`aiosqlite`). Alembic for migrations. The local `connectors` package handles Polymarket. Jinja2 renders the digest. No model, no simulator, no sentiment, no rationale generation in this plan — those land in Plans 2–5.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, SQLModel, Alembic, aiosqlite, APScheduler, httpx, pydantic-settings, structlog, Jinja2, connectors (local), pytest + pytest-asyncio, ruff, uv.

**Plan sequence (context only — not in scope here):**
- Plan 1 (this): Foundations + thin pipeline (Polymarket-as-forecast)
- Plan 2: Sports-data ingest extensions + Elo + match model
- Plan 3: Monte Carlo simulator + tournament outlook
- Plan 4: News/Reddit ingest + Claude-written rationales
- Plan 5: Top-scorer model
- Plan 6: HTMX dashboard + MCP exposure + deployment

---

## File structure created in this plan

```
worldcap/
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py
│       └── 0002_forecast_snapshots.py
├── scripts/
│   └── seed_competition.py
├── src/worldcap/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── log.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── tournament.py        # Competition, TournamentFormat, Team, Match
│   │   ├── odds.py              # OddsSnapshot
│   │   └── forecast.py          # ForecastSnapshot, TournamentForecast
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── sports_data.py       # football-data.org client
│   │   ├── fixtures.py          # ingest teams + fixtures into DB
│   │   └── polymarket.py        # ingest outright winner market into DB
│   ├── model/
│   │   └── naive.py             # Polymarket-as-forecast generator
│   ├── render/
│   │   ├── __init__.py
│   │   ├── markdown.py          # jinja2-based renderer
│   │   ├── templates/
│   │   │   └── digest_pretournament.md.j2
│   │   └── writer.py            # writes digest + WhatsApp pickup file
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── refresh.py           # full pipeline run
│   │   └── scheduler.py         # APScheduler daily trigger
│   └── api/
│       ├── __init__.py
│       └── app.py               # FastAPI app, endpoints, lifespan
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_db.py
    ├── test_sports_data.py
    ├── test_fixtures.py
    ├── test_polymarket.py
    ├── test_naive.py
    ├── test_markdown.py
    ├── test_writer.py
    ├── test_refresh.py
    ├── test_scheduler.py
    └── test_app.py
```

The `connectors` package is consumed as an editable local install from `/Users/ziv.a/repos_/collectors/collectors` (no changes made to it).

---

## Task 1: Repo scaffolding + dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/worldcap/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "worldcap"
version = "0.1.0"
description = "World Cup 2026 pre-match forecast feed"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlmodel>=0.0.22",
    "aiosqlite>=0.20.0",
    "alembic>=1.14.0",
    "greenlet>=3.0.0",
    "apscheduler>=3.10.0",
    "httpx>=0.27.0",
    "pydantic-settings>=2.5.0",
    "structlog>=24.4.0",
    "jinja2>=3.1.0",
    "connectors[polymarket] @ file:///Users/ziv.a/repos_/collectors/collectors",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.7.0",
    "respx>=0.21.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/worldcap"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.env
*.db
*.db-journal
output/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Database
DATABASE_URL=sqlite+aiosqlite:///./worldcap.db

# football-data.org API key — register at https://www.football-data.org/client/register
FOOTBALL_DATA_API_KEY=

# Output paths
DIGEST_OUTPUT_DIR=./output
WHATSAPP_PICKUP_PATH=./output/latest.md

# Daily refresh time (cron format, local time)
DAILY_REFRESH_CRON=0 9 * * *

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 4: Write minimal `README.md`**

```markdown
# worldcap

World Cup 2026 pre-match forecast feed. See `docs/specs/2026-05-21-worldcap-design.md`.

## Quick start

    uv sync
    cp .env.example .env  # fill in FOOTBALL_DATA_API_KEY
    uv run alembic upgrade head
    uv run python scripts/seed_competition.py
    uv run uvicorn worldcap.api.app:app --reload
```

- [ ] **Step 5: Create empty package files**

```bash
mkdir -p src/worldcap tests
touch src/worldcap/__init__.py tests/__init__.py
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
import asyncio
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Each test gets its own SQLite file and output dir."""
    db_path = tmp_path / "worldcap.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(output_dir / "latest.md"))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield
```

- [ ] **Step 7: Sync dependencies**

Run: `uv sync --all-extras`
Expected: clean exit, `.venv/` populated.

- [ ] **Step 8: Verify pytest can discover tests**

Run: `uv run pytest -q`
Expected: `no tests ran` (no tests yet) — confirms pytest works.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md src tests
git commit -m "chore: repo scaffolding + dependencies"
```

---

## Task 2: Config module

**Files:**
- Create: `src/worldcap/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'worldcap.config'`.

- [ ] **Step 3: Implement `src/worldcap/config.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./worldcap.db"
    football_data_api_key: str = ""
    digest_output_dir: Path = Path("./output")
    whatsapp_pickup_path: Path = Path("./output/latest.md")
    daily_refresh_cron: str = "0 9 * * *"
    log_level: str = "INFO"

    competition_code: str = "WC"  # football-data.org code for World Cup
    competition_season: int = 2026


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test (expect pass)**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/config.py tests/test_config.py
git commit -m "feat: config module with pydantic-settings"
```

---

## Task 3: Logging + database setup

**Files:**
- Create: `src/worldcap/log.py`
- Create: `src/worldcap/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write `src/worldcap/log.py`**

```python
import logging
import sys

import structlog

from worldcap.config import get_settings


def configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 2: Write failing test**

`tests/test_db.py`:

```python
import pytest
from sqlmodel import SQLModel

from worldcap.db import create_engine_, get_session, init_db


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "x.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    from worldcap.config import get_settings
    get_settings.cache_clear()

    await init_db()
    assert db_file.exists()


@pytest.mark.asyncio
async def test_get_session_yields_usable_session():
    await init_db()
    async with get_session() as session:
        from sqlmodel import text
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
```

- [ ] **Step 3: Run test (expect failure)**

Run: `uv run pytest tests/test_db.py -v`
Expected: `ModuleNotFoundError: No module named 'worldcap.db'`.

- [ ] **Step 4: Implement `src/worldcap/db.py`**

```python
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from worldcap.config import get_settings


@lru_cache
def create_engine_():
    return create_async_engine(get_settings().database_url, future=True, echo=False)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_engine_(), class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables from SQLModel metadata. Alembic migrations are authoritative;
    this exists for tests."""
    engine = create_engine_()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_session():
    async with _sessionmaker()() as session:
        yield session


def reset_engine_cache() -> None:
    """Called by tests when DATABASE_URL changes mid-process."""
    create_engine_.cache_clear()
    _sessionmaker.cache_clear()
```

- [ ] **Step 5: Update `tests/test_db.py` to reset engine cache**

Replace the top of each test with the cache reset. Final file:

```python
import pytest
from sqlalchemy import text

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "x.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()
    reset_engine_cache()

    await init_db()
    assert db_file.exists()


@pytest.mark.asyncio
async def test_get_session_yields_usable_session():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    async with get_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
```

- [ ] **Step 6: Run test (expect pass)**

Run: `uv run pytest tests/test_db.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/worldcap/log.py src/worldcap/db.py tests/test_db.py
git commit -m "feat: db + logging foundations"
```

---

## Task 4: Domain models — tournament structure

**Files:**
- Create: `src/worldcap/models/__init__.py`
- Create: `src/worldcap/models/tournament.py`

- [ ] **Step 1: Write `src/worldcap/models/tournament.py`**

```python
from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class TournamentFormat(SQLModel, table=True):
    __tablename__ = "tournament_format"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    groups_n: int
    group_size: int
    knockout_size: int  # number of teams entering the knockout stage
    tiebreaker_rules: list[str] = Field(sa_column=Column(JSON), default_factory=list)


class Competition(SQLModel, table=True):
    __tablename__ = "competition"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    code: str = Field(index=True, unique=True)  # e.g. "WC2026"
    format_id: int = Field(foreign_key="tournament_format.id")
    start_date: datetime
    end_date: datetime


class Team(SQLModel, table=True):
    __tablename__ = "team"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: int = Field(index=True, unique=True)  # football-data.org team id
    name: str
    country_code: Optional[str] = None
    fifa_rank: Optional[int] = None


class Match(SQLModel, table=True):
    __tablename__ = "match"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: int = Field(index=True, unique=True)  # football-data.org match id
    competition_id: int = Field(foreign_key="competition.id")
    stage: str  # group | R32 | R16 | QF | SF | F | 3rd
    group_label: Optional[str] = None  # "A".."L" for WC26
    home_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    away_team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    kickoff_utc: datetime
    status: str = "SCHEDULED"  # SCHEDULED | LIVE | FT | POSTPONED
    home_score: Optional[int] = None
    away_score: Optional[int] = None
```

- [ ] **Step 2: Write `src/worldcap/models/__init__.py`**

```python
from worldcap.models.tournament import Competition, Match, Team, TournamentFormat

__all__ = ["Competition", "Match", "Team", "TournamentFormat"]
```

- [ ] **Step 3: Verify the package imports**

Run: `uv run python -c "from worldcap.models import Competition, Match, Team, TournamentFormat; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/worldcap/models/
git commit -m "feat: tournament/team/match domain models"
```

---

## Task 5: Alembic setup + initial migration

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_initial_schema.py`

- [ ] **Step 1: Initialize alembic**

Run: `uv run alembic init -t async migrations`
Expected: creates `alembic.ini` + `migrations/` skeleton.

- [ ] **Step 2: Edit `alembic.ini`** — set `sqlalchemy.url` to be loaded from env:

Replace the `sqlalchemy.url = ...` line with an empty value (env.py will set it):

```ini
sqlalchemy.url =
```

- [ ] **Step 3: Replace `migrations/env.py`** with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

import worldcap.models  # noqa: F401  ensures models are imported for autogenerate
from worldcap.config import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate initial migration**

Run: `uv run alembic revision --autogenerate -m "initial schema"`
Expected: creates `migrations/versions/<hash>_initial_schema.py`.

- [ ] **Step 5: Rename the migration file** to `0001_initial_schema.py` and edit the `down_revision` to `None`, `revision` to `"0001"`. Verify the migration body contains `op.create_table("tournament_format", ...)`, `op.create_table("competition", ...)`, `op.create_table("team", ...)`, `op.create_table("match", ...)`.

- [ ] **Step 6: Apply migration to a scratch DB**

Run: `rm -f worldcap.db && uv run alembic upgrade head && sqlite3 worldcap.db ".tables"`
Expected: prints `alembic_version  competition  match  team  tournament_format`.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini migrations/
git commit -m "feat: alembic migrations + initial schema"
```

---

## Task 6: Seed WC 2026 competition row

**Files:**
- Create: `scripts/seed_competition.py`
- Create: `tests/test_seed_competition.py`

- [ ] **Step 1: Write failing test**

`tests/test_seed_competition.py`:

```python
import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.models import Competition, TournamentFormat
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_seed_inserts_competition_and_format():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()

    await seed()

    async with get_session() as session:
        comps = (await session.execute(select(Competition))).scalars().all()
        formats = (await session.execute(select(TournamentFormat))).scalars().all()

    assert len(comps) == 1
    assert comps[0].code == "WC2026"
    assert len(formats) == 1
    assert formats[0].groups_n == 12
    assert formats[0].group_size == 4
    assert formats[0].knockout_size == 32


@pytest.mark.asyncio
async def test_seed_is_idempotent():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()

    await seed()
    await seed()

    async with get_session() as session:
        comps = (await session.execute(select(Competition))).scalars().all()
    assert len(comps) == 1
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_seed_competition.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Implement `scripts/seed_competition.py`**

```python
"""Seed the WC 2026 competition row + tournament format. Idempotent."""

import asyncio
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import Competition, TournamentFormat


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

WC2026 = Competition(
    name="FIFA World Cup 2026",
    code="WC2026",
    format_id=0,  # filled in after format insert
    start_date=datetime(2026, 6, 11, tzinfo=timezone.utc),
    end_date=datetime(2026, 7, 19, tzinfo=timezone.utc),
)


async def seed() -> None:
    async with get_session() as session:
        existing = (await session.execute(select(Competition).where(Competition.code == "WC2026"))).scalar_one_or_none()
        if existing:
            return

        fmt = TournamentFormat(**WC2026_FORMAT.model_dump(exclude={"id"}))
        session.add(fmt)
        await session.flush()

        comp = Competition(**WC2026.model_dump(exclude={"id", "format_id"}), format_id=fmt.id)
        session.add(comp)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] **Step 4: Make `scripts/` importable**

Run: `touch scripts/__init__.py`

- [ ] **Step 5: Run test (expect pass)**

Run: `uv run pytest tests/test_seed_competition.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/ tests/test_seed_competition.py
git commit -m "feat: seed WC 2026 competition + tournament format"
```

---

## Task 7: Sports-data API client

**Files:**
- Create: `src/worldcap/ingest/__init__.py`
- Create: `src/worldcap/ingest/sports_data.py`
- Create: `tests/test_sports_data.py`

- [ ] **Step 1: Write failing test**

`tests/test_sports_data.py`:

```python
import httpx
import pytest
import respx

from worldcap.ingest.sports_data import (
    FootballDataClient,
    TeamDTO,
    FixtureDTO,
)


@pytest.mark.asyncio
async def test_get_teams(respx_mock: respx.MockRouter):
    respx_mock.get("https://api.football-data.org/v4/competitions/WC/teams").mock(
        return_value=httpx.Response(
            200,
            json={
                "teams": [
                    {"id": 759, "name": "Brazil", "tla": "BRA"},
                    {"id": 760, "name": "France", "tla": "FRA"},
                ]
            },
        )
    )
    client = FootballDataClient(api_key="k")
    teams = await client.get_teams("WC")
    assert teams == [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]


@pytest.mark.asyncio
async def test_get_fixtures(respx_mock: respx.MockRouter):
    respx_mock.get("https://api.football-data.org/v4/competitions/WC/matches").mock(
        return_value=httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 1,
                        "stage": "GROUP_STAGE",
                        "group": "GROUP_A",
                        "utcDate": "2026-06-11T20:00:00Z",
                        "status": "SCHEDULED",
                        "homeTeam": {"id": 759},
                        "awayTeam": {"id": 760},
                        "score": {"fullTime": {"home": None, "away": None}},
                    }
                ]
            },
        )
    )
    client = FootballDataClient(api_key="k")
    fixtures = await client.get_fixtures("WC")
    assert len(fixtures) == 1
    f = fixtures[0]
    assert f.external_id == 1
    assert f.stage == "group"
    assert f.group_label == "A"
    assert f.home_external_id == 759
    assert f.away_external_id == 760
    assert f.status == "SCHEDULED"
```

- [ ] **Step 2: Add `respx_mock` fixture**

`tests/conftest.py` — append:

```python
import respx


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
```

- [ ] **Step 3: Run test (expect failure)**

Run: `uv run pytest tests/test_sports_data.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `src/worldcap/ingest/__init__.py`**

```python
```

(empty)

- [ ] **Step 5: Implement `src/worldcap/ingest/sports_data.py`**

```python
from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel


API_BASE = "https://api.football-data.org/v4"

_STAGE_MAP = {
    "GROUP_STAGE": "group",
    "LAST_32": "R32",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "FINAL": "F",
    "THIRD_PLACE": "3rd",
}


class TeamDTO(BaseModel):
    external_id: int
    name: str
    country_code: Optional[str] = None


class FixtureDTO(BaseModel):
    external_id: int
    stage: str
    group_label: Optional[str]
    kickoff_utc: datetime
    status: str
    home_external_id: Optional[int]
    away_external_id: Optional[int]
    home_score: Optional[int]
    away_score: Optional[int]


class FootballDataClient:
    def __init__(self, api_key: str, base_url: str = API_BASE, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Auth-Token": api_key} if api_key else {},
            timeout=timeout,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_teams(self, competition_code: str) -> list[TeamDTO]:
        r = await self._client.get(f"/competitions/{competition_code}/teams")
        r.raise_for_status()
        data = r.json()
        return [
            TeamDTO(
                external_id=t["id"],
                name=t["name"],
                country_code=t.get("tla"),
            )
            for t in data.get("teams", [])
        ]

    async def get_fixtures(self, competition_code: str) -> list[FixtureDTO]:
        r = await self._client.get(f"/competitions/{competition_code}/matches")
        r.raise_for_status()
        data = r.json()
        out: list[FixtureDTO] = []
        for m in data.get("matches", []):
            stage = _STAGE_MAP.get(m.get("stage", ""), m.get("stage", "").lower())
            group_raw = m.get("group")
            group_label = group_raw.removeprefix("GROUP_") if group_raw else None
            score = m.get("score", {}).get("fullTime", {})
            out.append(
                FixtureDTO(
                    external_id=m["id"],
                    stage=stage,
                    group_label=group_label,
                    kickoff_utc=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
                    status=m.get("status", "SCHEDULED"),
                    home_external_id=(m.get("homeTeam") or {}).get("id"),
                    away_external_id=(m.get("awayTeam") or {}).get("id"),
                    home_score=score.get("home"),
                    away_score=score.get("away"),
                )
            )
        return out
```

- [ ] **Step 6: Run test (expect pass)**

Run: `uv run pytest tests/test_sports_data.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/worldcap/ingest/ tests/test_sports_data.py tests/conftest.py
git commit -m "feat: football-data.org client (teams + fixtures)"
```

---

## Task 8: Fixtures ingest pipeline

**Files:**
- Create: `src/worldcap/ingest/fixtures.py`
- Create: `tests/test_fixtures.py`

- [ ] **Step 1: Write failing test**

`tests/test_fixtures.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.ingest.fixtures import ingest_teams_and_fixtures
from worldcap.ingest.sports_data import FixtureDTO, TeamDTO
from worldcap.models import Match, Team
from scripts.seed_competition import seed


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.get_teams.return_value = [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]
    client.get_fixtures.return_value = [
        FixtureDTO(
            external_id=1001,
            stage="group",
            group_label="A",
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
            home_external_id=759,
            away_external_id=760,
            home_score=None,
            away_score=None,
        )
    ]
    return client


@pytest.mark.asyncio
async def test_ingest_creates_rows(fake_client):
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    summary = await ingest_teams_and_fixtures(fake_client)

    assert summary == {"teams_upserted": 2, "matches_upserted": 1}
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        matches = (await session.execute(select(Match))).scalars().all()
    assert len(teams) == 2
    assert len(matches) == 1
    assert matches[0].home_team_id is not None
    assert matches[0].away_team_id is not None


@pytest.mark.asyncio
async def test_ingest_is_idempotent(fake_client):
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    await ingest_teams_and_fixtures(fake_client)
    await ingest_teams_and_fixtures(fake_client)

    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        matches = (await session.execute(select(Match))).scalars().all()
    assert len(teams) == 2
    assert len(matches) == 1
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_fixtures.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/worldcap/ingest/fixtures.py`**

```python
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.ingest.sports_data import FootballDataClient
from worldcap.models import Competition, Match, Team


async def ingest_teams_and_fixtures(client: FootballDataClient) -> dict[str, int]:
    settings = get_settings()
    teams_dto = await client.get_teams(settings.competition_code)
    fixtures_dto = await client.get_fixtures(settings.competition_code)

    teams_upserted = 0
    matches_upserted = 0

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == "WC2026")
        )).scalar_one()

        # Upsert teams
        existing_by_ext = {
            t.external_id: t
            for t in (await session.execute(select(Team))).scalars().all()
        }
        for dto in teams_dto:
            if dto.external_id in existing_by_ext:
                row = existing_by_ext[dto.external_id]
                changed = False
                if row.name != dto.name:
                    row.name = dto.name
                    changed = True
                if row.country_code != dto.country_code:
                    row.country_code = dto.country_code
                    changed = True
                if changed:
                    teams_upserted += 1
            else:
                session.add(Team(
                    external_id=dto.external_id,
                    name=dto.name,
                    country_code=dto.country_code,
                ))
                teams_upserted += 1
        await session.flush()

        # Refresh team map
        ext_to_id = {
            t.external_id: t.id
            for t in (await session.execute(select(Team))).scalars().all()
        }

        # Upsert matches
        existing_matches = {
            m.external_id: m
            for m in (await session.execute(select(Match))).scalars().all()
        }
        for dto in fixtures_dto:
            home_id = ext_to_id.get(dto.home_external_id) if dto.home_external_id else None
            away_id = ext_to_id.get(dto.away_external_id) if dto.away_external_id else None
            if dto.external_id in existing_matches:
                row = existing_matches[dto.external_id]
                row.home_team_id = home_id
                row.away_team_id = away_id
                row.kickoff_utc = dto.kickoff_utc
                row.status = dto.status
                row.home_score = dto.home_score
                row.away_score = dto.away_score
                matches_upserted += 1
            else:
                session.add(Match(
                    external_id=dto.external_id,
                    competition_id=comp.id,
                    stage=dto.stage,
                    group_label=dto.group_label,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    kickoff_utc=dto.kickoff_utc,
                    status=dto.status,
                    home_score=dto.home_score,
                    away_score=dto.away_score,
                ))
                matches_upserted += 1

        await session.commit()

    # Idempotency: a no-change upsert is not counted
    return {"teams_upserted": teams_upserted, "matches_upserted": matches_upserted}
```

Note: the idempotency test expects `teams_upserted=2, matches_upserted=1` on first run, then a re-run is expected to leave the counts at 2/1 (same rows). The test asserts row counts, not return values on the second call. The implementation counts upserts including no-op updates on matches; this is intentional since matches may have status/score changes that should still be considered "touched". If we want strict idempotency in the return value too, we'd compare fields — left as a follow-up.

- [ ] **Step 4: Run test (expect pass)**

Run: `uv run pytest tests/test_fixtures.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/ingest/fixtures.py tests/test_fixtures.py
git commit -m "feat: ingest teams + fixtures from football-data.org"
```

---

## Task 9: OddsSnapshot model + migration

**Files:**
- Create: `src/worldcap/models/odds.py`
- Modify: `src/worldcap/models/__init__.py`
- Create: `migrations/versions/0002_odds_and_forecasts.py` (we'll add forecast tables in Task 10 in the same migration — defer the file until then)

- [ ] **Step 1: Write `src/worldcap/models/odds.py`**

```python
from datetime import datetime
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


class OddsSnapshot(SQLModel, table=True):
    __tablename__ = "odds_snapshot"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    match_id: Optional[int] = Field(default=None, foreign_key="match.id", index=True)
    market_type: str  # match_3way | outright_winner | stage_advancement | top_scorer
    source: str = "polymarket"
    ts: datetime
    outcomes: dict = Field(sa_column=Column(JSON))
    volume: Optional[float] = None
```

- [ ] **Step 2: Update `src/worldcap/models/__init__.py`**

```python
from worldcap.models.tournament import Competition, Match, Team, TournamentFormat
from worldcap.models.odds import OddsSnapshot

__all__ = [
    "Competition", "Match", "Team", "TournamentFormat",
    "OddsSnapshot",
]
```

- [ ] **Step 3: Verify the package imports**

Run: `uv run python -c "from worldcap.models import OddsSnapshot; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit (migration is generated together with forecast tables in Task 10)**

```bash
git add src/worldcap/models/odds.py src/worldcap/models/__init__.py
git commit -m "feat: OddsSnapshot model"
```

---

## Task 10: Forecast snapshot models + migration

**Files:**
- Create: `src/worldcap/models/forecast.py`
- Modify: `src/worldcap/models/__init__.py`
- Create: `migrations/versions/0002_odds_and_forecasts.py`

- [ ] **Step 1: Write `src/worldcap/models/forecast.py`**

```python
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ForecastSnapshot(SQLModel, table=True):
    __tablename__ = "forecast_snapshot"

    id: Optional[int] = Field(default=None, primary_key=True)
    competition_id: int = Field(foreign_key="competition.id", index=True)
    snapshot_date: datetime
    snapshot_trigger: str  # daily | post_match | manual
    state_hash: str
    model_version: str = "naive-poly-only-v0"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TournamentForecast(SQLModel, table=True):
    __tablename__ = "tournament_forecast"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="forecast_snapshot.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    p_champion: float
    p_runner_up: float = 0.0
    p_semi: float = 0.0
    p_top_group: float = 0.0
    poly_p_champion: Optional[float] = None
    edge_vs_poly: float = 0.0
```

- [ ] **Step 2: Update `src/worldcap/models/__init__.py`**

```python
from worldcap.models.tournament import Competition, Match, Team, TournamentFormat
from worldcap.models.odds import OddsSnapshot
from worldcap.models.forecast import ForecastSnapshot, TournamentForecast

__all__ = [
    "Competition", "Match", "Team", "TournamentFormat",
    "OddsSnapshot",
    "ForecastSnapshot", "TournamentForecast",
]
```

- [ ] **Step 3: Generate migration**

Run: `uv run alembic revision --autogenerate -m "odds and forecasts"`
Expected: new migration file under `migrations/versions/`. Rename it to `0002_odds_and_forecasts.py`, set `down_revision = "0001"`, `revision = "0002"`. Verify body creates `odds_snapshot`, `forecast_snapshot`, `tournament_forecast`.

- [ ] **Step 4: Apply migration**

Run: `rm -f worldcap.db && uv run alembic upgrade head && sqlite3 worldcap.db ".tables"`
Expected: lists all six tables plus `alembic_version`.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/models/forecast.py src/worldcap/models/__init__.py migrations/versions/
git commit -m "feat: forecast snapshot models + migration"
```

---

## Task 11: Polymarket ingest

**Files:**
- Create: `src/worldcap/ingest/polymarket.py`
- Create: `tests/test_polymarket.py`

- [ ] **Step 1: Write failing test**

`tests/test_polymarket.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.ingest.polymarket import ingest_outright_winner
from worldcap.models import OddsSnapshot, Team
from scripts.seed_competition import seed


@pytest.fixture
def fake_poly_collector():
    """Mimics connectors.polymarket.PolymarketCollector for outright winner."""
    collector = MagicMock()
    market = MagicMock()
    market.question = "Winner of FIFA World Cup 2026"
    market.outcomes = ["Brazil", "France"]
    market.outcome_prices = [0.25, 0.18]
    market.volume = 100000.0
    result = MagicMock()
    result.status = "success"
    result.markets = [market]
    collector.fetch_markets = AsyncMock(return_value=result)
    return collector


@pytest.mark.asyncio
async def test_ingest_outright_persists_snapshot(fake_poly_collector):
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.commit()

    summary = await ingest_outright_winner(fake_poly_collector)
    assert summary["snapshots_inserted"] == 1
    assert summary["teams_matched"] == 2

    async with get_session() as session:
        snaps = (await session.execute(select(OddsSnapshot))).scalars().all()
    assert len(snaps) == 1
    assert snaps[0].market_type == "outright_winner"
    assert pytest.approx(snaps[0].outcomes["Brazil"], rel=1e-6) == 0.25
    assert pytest.approx(snaps[0].outcomes["France"], rel=1e-6) == 0.18


@pytest.mark.asyncio
async def test_ingest_outright_handles_no_match(fake_poly_collector):
    fake_poly_collector.fetch_markets.return_value.status = "success"
    fake_poly_collector.fetch_markets.return_value.markets = []

    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    summary = await ingest_outright_winner(fake_poly_collector)
    assert summary == {"snapshots_inserted": 0, "teams_matched": 0}
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_polymarket.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/worldcap/ingest/polymarket.py`**

```python
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import Competition, OddsSnapshot, Team

OUTRIGHT_QUERY = "FIFA World Cup 2026 winner"


def _find_outright_winner_market(markets):
    """Heuristic: the market whose question contains 'World Cup 2026' and 'winner'."""
    for m in markets:
        q = (m.question or "").lower()
        if "world cup 2026" in q and "winner" in q:
            return m
    return None


async def ingest_outright_winner(collector) -> dict[str, int]:
    """Pulls the WC 2026 outright winner market from Polymarket and writes one OddsSnapshot row."""
    # Avoid importing connectors at module import time; the caller passes in the collector.
    # If the caller wants discovery, they should pass a collector that has already searched.
    from connectors.polymarket import MarketCollectSpec  # noqa: WPS433

    spec = MarketCollectSpec(active=True, order="volume", ascending=False, limit=50)
    result = await collector.fetch_markets(spec)
    if result.status != "success" or not result.markets:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    market = _find_outright_winner_market(result.markets)
    if market is None:
        return {"snapshots_inserted": 0, "teams_matched": 0}

    outcomes = {o: p for o, p in zip(market.outcomes, market.outcome_prices)}

    async with get_session() as session:
        comp = (await session.execute(
            select(Competition).where(Competition.code == "WC2026")
        )).scalar_one()
        teams = (await session.execute(select(Team))).scalars().all()
        team_names = {t.name for t in teams}
        teams_matched = sum(1 for name in outcomes if name in team_names)

        snap = OddsSnapshot(
            competition_id=comp.id,
            match_id=None,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime.now(timezone.utc),
            outcomes=outcomes,
            volume=getattr(market, "volume", None),
        )
        session.add(snap)
        await session.commit()

    return {"snapshots_inserted": 1, "teams_matched": teams_matched}
```

- [ ] **Step 4: Run test (expect pass)**

Run: `uv run pytest tests/test_polymarket.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/ingest/polymarket.py tests/test_polymarket.py
git commit -m "feat: ingest Polymarket outright winner market"
```

---

## Task 12: Naive forecast generator

**Files:**
- Create: `src/worldcap/model/__init__.py`
- Create: `src/worldcap/model/naive.py`
- Create: `tests/test_naive.py`

- [ ] **Step 1: Write failing test**

`tests/test_naive.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.model.naive import generate_naive_forecast
from worldcap.models import ForecastSnapshot, OddsSnapshot, Team, TournamentForecast
from worldcap.models.tournament import Competition
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_naive_forecast_uses_latest_outright_snapshot():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    async with get_session() as session:
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
            Team(external_id=761, name="Argentina", country_code="ARG"),
        ])
        await session.flush()

        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "France": 0.18, "Argentina": 0.17},
            volume=100000.0,
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")

    async with get_session() as session:
        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()

    assert len(forecasts) == 3
    by_team = {f.team_id: f for f in forecasts}
    brazil = (await get_session_team_by_name("Brazil"))
    assert pytest.approx(by_team[brazil.id].p_champion, rel=1e-6) == 0.25
    assert by_team[brazil.id].edge_vs_poly == 0.0
    assert snap.model_version == "naive-poly-only-v0"


async def get_session_team_by_name(name: str) -> Team:
    async with get_session() as session:
        return (await session.execute(select(Team).where(Team.name == name))).scalar_one()


@pytest.mark.asyncio
async def test_naive_forecast_skips_unknown_team_names():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    async with get_session() as session:
        session.add(Team(external_id=759, name="Brazil", country_code="BRA"))
        await session.flush()

        comp = (await session.execute(select(Competition))).scalar_one()
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "Eldorado": 0.05},  # second team not seeded
            volume=None,
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")

    async with get_session() as session:
        rows = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snap.id)
        )).scalars().all()
    assert len(rows) == 1  # only Brazil matched a Team row
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_naive.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/worldcap/model/__init__.py`**

```python
```

(empty)

- [ ] **Step 4: Implement `src/worldcap/model/naive.py`**

```python
import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    OddsSnapshot,
    Team,
    TournamentForecast,
)


def _state_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


async def generate_naive_forecast(trigger: str = "manual") -> ForecastSnapshot:
    """Write a ForecastSnapshot whose tournament-level probabilities are the latest
    Polymarket outright-winner odds, mapped onto Team rows. edge_vs_poly is 0.
    Returns the persisted ForecastSnapshot."""

    async with get_session() as session:
        comp = (await session.execute(select(Competition).where(Competition.code == "WC2026"))).scalar_one()

        latest = (await session.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.competition_id == comp.id)
            .where(OddsSnapshot.market_type == "outright_winner")
            .order_by(OddsSnapshot.ts.desc())
        )).scalars().first()

        if latest is None:
            outcomes: dict[str, float] = {}
        else:
            outcomes = dict(latest.outcomes)

        teams = (await session.execute(select(Team))).scalars().all()
        team_by_name = {t.name: t for t in teams}

        snap = ForecastSnapshot(
            competition_id=comp.id,
            snapshot_date=datetime.now(timezone.utc),
            snapshot_trigger=trigger,
            state_hash=_state_hash(outcomes),
            model_version="naive-poly-only-v0",
        )
        session.add(snap)
        await session.flush()

        for name, p in outcomes.items():
            team = team_by_name.get(name)
            if team is None:
                continue
            session.add(TournamentForecast(
                snapshot_id=snap.id,
                team_id=team.id,
                p_champion=float(p),
                poly_p_champion=float(p),
                edge_vs_poly=0.0,
            ))

        await session.commit()
        await session.refresh(snap)
        return snap
```

- [ ] **Step 5: Run test (expect pass)**

Run: `uv run pytest tests/test_naive.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/worldcap/model/ tests/test_naive.py
git commit -m "feat: naive forecast generator (Polymarket-as-forecast)"
```

---

## Task 13: Markdown renderer

**Files:**
- Create: `src/worldcap/render/__init__.py`
- Create: `src/worldcap/render/templates/digest_pretournament.md.j2`
- Create: `src/worldcap/render/markdown.py`
- Create: `tests/test_markdown.py`

- [ ] **Step 1: Write failing test**

`tests/test_markdown.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.model.naive import generate_naive_forecast
from worldcap.models import OddsSnapshot, Team
from worldcap.models.tournament import Competition, Match
from worldcap.render.markdown import render_digest_markdown
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_renders_pretournament_digest_with_outlook_and_next_fixtures():
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=759, name="Brazil", country_code="BRA"),
            Team(external_id=760, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        session.add(OddsSnapshot(
            competition_id=comp.id,
            market_type="outright_winner",
            source="polymarket",
            ts=datetime(2026, 5, 21, tzinfo=timezone.utc),
            outcomes={"Brazil": 0.25, "France": 0.18},
        ))
        session.add(Match(
            external_id=1,
            competition_id=comp.id,
            stage="group",
            group_label="A",
            home_team_id=teams["Brazil"].id,
            away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        ))
        await session.commit()

    snap = await generate_naive_forecast(trigger="manual")
    text = await render_digest_markdown(
        snapshot_id=snap.id,
        as_of=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert "World Cup" in text
    assert "T−" in text  # pre-tournament label
    assert "Tournament outlook" in text
    assert "Brazil" in text
    assert "25" in text  # 25%
    assert "Next matches" in text
    assert "Brazil vs France" in text
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_markdown.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/worldcap/render/__init__.py`**

```python
```

(empty)

- [ ] **Step 4: Create `src/worldcap/render/templates/digest_pretournament.md.j2`**

```jinja2
# World Cup — {{ as_of.strftime('%Y-%m-%d') }}  ·  {{ phase_label }}

## Tournament outlook

| # | Team | P(champion) | Polymarket | Edge |
|---|------|-------------|------------|------|
{%- for row in outlook %}
| {{ loop.index }} | {{ row.team_name }} | {{ '%.0f' % (row.p_champion * 100) }}% | {{ '%.0f' % (row.poly_p_champion * 100) }}% | {{ '%+.0fpp' % (row.edge_vs_poly * 100) }} |
{%- endfor %}

## Next matches

{%- for m in next_matches %}
- {{ m.home_name }} vs {{ m.away_name }} · {{ m.kickoff_utc.strftime('%Y-%m-%d %H:%M UTC') }} · Group {{ m.group_label }}
{%- endfor %}
```

- [ ] **Step 5: Implement `src/worldcap/render/markdown.py`**

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import select

from worldcap.db import get_session
from worldcap.models import Team, TournamentForecast
from worldcap.models.forecast import ForecastSnapshot
from worldcap.models.tournament import Competition, Match


TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class OutlookRow:
    team_name: str
    p_champion: float
    poly_p_champion: float
    edge_vs_poly: float


@dataclass
class NextMatchRow:
    home_name: str
    away_name: str
    kickoff_utc: datetime
    group_label: str | None


def _phase_label(as_of: datetime, start_date: datetime, end_date: datetime) -> str:
    if as_of < start_date:
        days = (start_date - as_of).days
        return f"T−{days} days · pre-tournament"
    if as_of <= end_date:
        return "in-tournament"
    return "post-tournament"


async def render_digest_markdown(snapshot_id: int, as_of: datetime, top_n: int = 10) -> str:
    async with get_session() as session:
        snap = (await session.execute(
            select(ForecastSnapshot).where(ForecastSnapshot.id == snapshot_id)
        )).scalar_one()
        comp = (await session.execute(
            select(Competition).where(Competition.id == snap.competition_id)
        )).scalar_one()

        forecasts = (await session.execute(
            select(TournamentForecast).where(TournamentForecast.snapshot_id == snapshot_id)
            .order_by(TournamentForecast.p_champion.desc())
            .limit(top_n)
        )).scalars().all()
        teams_by_id = {
            t.id: t
            for t in (await session.execute(select(Team))).scalars().all()
        }
        outlook = [
            OutlookRow(
                team_name=teams_by_id[f.team_id].name,
                p_champion=f.p_champion,
                poly_p_champion=f.poly_p_champion or f.p_champion,
                edge_vs_poly=f.edge_vs_poly,
            )
            for f in forecasts
        ]

        # Next 3 scheduled matches with both teams resolved
        upcoming = (await session.execute(
            select(Match)
            .where(Match.competition_id == comp.id)
            .where(Match.status == "SCHEDULED")
            .where(Match.kickoff_utc >= as_of)
            .order_by(Match.kickoff_utc.asc())
            .limit(20)  # over-fetch; we'll filter to those with both teams known
        )).scalars().all()
        next_matches: list[NextMatchRow] = []
        for m in upcoming:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            next_matches.append(NextMatchRow(
                home_name=teams_by_id[m.home_team_id].name,
                away_name=teams_by_id[m.away_team_id].name,
                kickoff_utc=m.kickoff_utc,
                group_label=m.group_label,
            ))
            if len(next_matches) >= 3:
                break

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(disabled_extensions=("j2",)),
    )
    tmpl = env.get_template("digest_pretournament.md.j2")
    return tmpl.render(
        as_of=as_of,
        phase_label=_phase_label(as_of, comp.start_date, comp.end_date),
        outlook=outlook,
        next_matches=next_matches,
    )
```

- [ ] **Step 6: Run test (expect pass)**

Run: `uv run pytest tests/test_markdown.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add src/worldcap/render/ tests/test_markdown.py
git commit -m "feat: pre-tournament markdown digest renderer"
```

---

## Task 14: Digest writer (file + pickup)

**Files:**
- Create: `src/worldcap/render/writer.py`
- Create: `tests/test_writer.py`

- [ ] **Step 1: Write failing test**

`tests/test_writer.py`:

```python
from pathlib import Path

import pytest

from worldcap.config import get_settings
from worldcap.render.writer import write_digest


@pytest.mark.asyncio
async def test_write_digest_writes_dated_file_and_pickup(tmp_path, monkeypatch):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    pickup = tmp_path / "out" / "latest.md"
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(pickup))
    get_settings.cache_clear()

    path = await write_digest("hello world\n", date_str="2026-05-21")

    assert path == output_dir / "2026-05-21.md"
    assert (output_dir / "2026-05-21.md").read_text() == "hello world\n"
    assert pickup.read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_write_digest_creates_missing_dirs(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(deep))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(deep / "latest.md"))
    get_settings.cache_clear()

    path = await write_digest("x", date_str="2026-05-22")

    assert path.exists()
    assert (deep / "latest.md").read_text() == "x"
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_writer.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/worldcap/render/writer.py`**

```python
from pathlib import Path

from worldcap.config import get_settings


async def write_digest(text: str, date_str: str) -> Path:
    settings = get_settings()
    settings.digest_output_dir.mkdir(parents=True, exist_ok=True)
    settings.whatsapp_pickup_path.parent.mkdir(parents=True, exist_ok=True)

    dated = settings.digest_output_dir / f"{date_str}.md"
    dated.write_text(text)
    settings.whatsapp_pickup_path.write_text(text)
    return dated
```

- [ ] **Step 4: Run test (expect pass)**

Run: `uv run pytest tests/test_writer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/render/writer.py tests/test_writer.py
git commit -m "feat: digest writer (dated file + WhatsApp pickup)"
```

---

## Task 15: Refresh orchestration

**Files:**
- Create: `src/worldcap/jobs/__init__.py`
- Create: `src/worldcap/jobs/refresh.py`
- Create: `tests/test_refresh.py`

- [ ] **Step 1: Write failing test**

`tests/test_refresh.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session, init_db, reset_engine_cache
from worldcap.ingest.sports_data import FixtureDTO, TeamDTO
from worldcap.jobs.refresh import run_refresh
from worldcap.models import ForecastSnapshot, OddsSnapshot, Team, TournamentForecast
from scripts.seed_competition import seed


@pytest.fixture
def fake_football_client():
    client = AsyncMock()
    client.get_teams.return_value = [
        TeamDTO(external_id=759, name="Brazil", country_code="BRA"),
        TeamDTO(external_id=760, name="France", country_code="FRA"),
    ]
    client.get_fixtures.return_value = [
        FixtureDTO(
            external_id=1,
            stage="group",
            group_label="A",
            kickoff_utc=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
            home_external_id=759,
            away_external_id=760,
            home_score=None,
            away_score=None,
        )
    ]
    return client


@pytest.fixture
def fake_poly_collector():
    market = MagicMock()
    market.question = "Winner of FIFA World Cup 2026"
    market.outcomes = ["Brazil", "France"]
    market.outcome_prices = [0.25, 0.18]
    market.volume = 100000.0
    result = MagicMock()
    result.status = "success"
    result.markets = [market]
    collector = MagicMock()
    collector.fetch_markets = AsyncMock(return_value=result)
    return collector


@pytest.mark.asyncio
async def test_run_refresh_end_to_end(fake_football_client, fake_poly_collector, monkeypatch):
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    snap = await run_refresh(
        trigger="manual",
        football_client=fake_football_client,
        poly_collector=fake_poly_collector,
        as_of=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert isinstance(snap, ForecastSnapshot)
    async with get_session() as session:
        teams = (await session.execute(select(Team))).scalars().all()
        odds = (await session.execute(select(OddsSnapshot))).scalars().all()
        forecasts = (await session.execute(select(TournamentForecast))).scalars().all()
    assert len(teams) == 2
    assert len(odds) == 1
    assert len(forecasts) == 2

    # Digest file written
    out_dir = get_settings().digest_output_dir
    assert (out_dir / "2026-05-21.md").exists()
    assert get_settings().whatsapp_pickup_path.exists()
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_refresh.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/worldcap/jobs/__init__.py`**

```python
```

(empty)

- [ ] **Step 4: Implement `src/worldcap/jobs/refresh.py`**

```python
from datetime import datetime, timezone
from typing import Optional

from worldcap.ingest.fixtures import ingest_teams_and_fixtures
from worldcap.ingest.polymarket import ingest_outright_winner
from worldcap.ingest.sports_data import FootballDataClient
from worldcap.log import get_logger
from worldcap.model.naive import generate_naive_forecast
from worldcap.models.forecast import ForecastSnapshot
from worldcap.render.markdown import render_digest_markdown
from worldcap.render.writer import write_digest


log = get_logger(__name__)


async def run_refresh(
    trigger: str,
    football_client,
    poly_collector,
    as_of: Optional[datetime] = None,
) -> ForecastSnapshot:
    """End-to-end pipeline: ingest -> forecast -> render -> write. Returns the snapshot."""

    as_of = as_of or datetime.now(timezone.utc)

    fixtures_summary = await ingest_teams_and_fixtures(football_client)
    log.info("ingest.fixtures", **fixtures_summary)

    odds_summary = await ingest_outright_winner(poly_collector)
    log.info("ingest.polymarket", **odds_summary)

    snap = await generate_naive_forecast(trigger=trigger)
    log.info("forecast.naive", snapshot_id=snap.id, model_version=snap.model_version)

    text = await render_digest_markdown(snapshot_id=snap.id, as_of=as_of)
    path = await write_digest(text, date_str=as_of.strftime("%Y-%m-%d"))
    log.info("render.digest", path=str(path))

    return snap
```

- [ ] **Step 5: Run test (expect pass)**

Run: `uv run pytest tests/test_refresh.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add src/worldcap/jobs/ tests/test_refresh.py
git commit -m "feat: refresh orchestration (ingest + forecast + render + write)"
```

---

## Task 16: APScheduler daily trigger

**Files:**
- Create: `src/worldcap/jobs/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing test**

`tests/test_scheduler.py`:

```python
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
    # spot-check cron fields
    fields = {f.name: str(f) for f in trigger.fields}
    assert fields["minute"] == "30"
    assert fields["hour"] == "9"
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/worldcap/jobs/scheduler.py`**

```python
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
```

- [ ] **Step 4: Run test (expect pass)**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/worldcap/jobs/scheduler.py tests/test_scheduler.py
git commit -m "feat: APScheduler daily trigger"
```

---

## Task 17: FastAPI app + endpoints + lifespan

**Files:**
- Create: `src/worldcap/api/__init__.py`
- Create: `src/worldcap/api/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing test**

`tests/test_app.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from worldcap.api.app import build_app
from worldcap.config import get_settings
from worldcap.db import init_db, reset_engine_cache
from scripts.seed_competition import seed


@pytest.fixture
def fake_clients():
    football = AsyncMock()
    football.get_teams.return_value = []
    football.get_fixtures.return_value = []
    poly_market = MagicMock()
    poly_market.question = "Winner of FIFA World Cup 2026"
    poly_market.outcomes = []
    poly_market.outcome_prices = []
    poly_market.volume = 0
    poly_result = MagicMock()
    poly_result.status = "success"
    poly_result.markets = [poly_market]
    poly = MagicMock()
    poly.fetch_markets = AsyncMock(return_value=poly_result)
    return football, poly


@pytest.mark.asyncio
async def test_healthz_ok():
    get_settings.cache_clear()
    reset_engine_cache()
    app = build_app(football_client=AsyncMock(), poly_collector=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_post_refresh_runs_pipeline(fake_clients):
    get_settings.cache_clear()
    reset_engine_cache()
    await init_db()
    await seed()

    football, poly = fake_clients
    app = build_app(football_client=football, poly_collector=poly)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot_id"] >= 1
    assert body["trigger"] == "manual"
```

- [ ] **Step 2: Run test (expect failure)**

Run: `uv run pytest tests/test_app.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/worldcap/api/__init__.py`**

```python
```

(empty)

- [ ] **Step 4: Implement `src/worldcap/api/app.py`**

```python
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from sqlmodel import select

from worldcap.config import get_settings
from worldcap.db import get_session
from worldcap.jobs.refresh import run_refresh
from worldcap.jobs.scheduler import build_scheduler
from worldcap.log import configure_logging, get_logger
from worldcap.models import ForecastSnapshot, Team, TournamentForecast


log = get_logger(__name__)


def _default_clients():
    """Production client builders. Imported lazily so tests don't need real keys."""
    from connectors.polymarket import PolymarketClientConfig, PolymarketCollector

    from worldcap.ingest.sports_data import FootballDataClient

    settings = get_settings()
    football = FootballDataClient(api_key=settings.football_data_api_key)
    poly = PolymarketCollector(PolymarketClientConfig(timeout=30))
    return football, poly


def build_app(football_client=None, poly_collector=None) -> FastAPI:
    configure_logging()

    if football_client is None or poly_collector is None:
        football_client, poly_collector = _default_clients()

    async def _trigger_refresh(trigger: str = "manual"):
        return await run_refresh(
            trigger=trigger,
            football_client=football_client,
            poly_collector=poly_collector,
            as_of=datetime.now(timezone.utc),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = build_scheduler(refresh_fn=lambda: _trigger_refresh("daily"))
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            if hasattr(football_client, "aclose"):
                await football_client.aclose()

    app = FastAPI(title="worldcap", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/refresh")
    async def refresh():
        snap = await _trigger_refresh("manual")
        return {"snapshot_id": snap.id, "trigger": snap.snapshot_trigger}

    @app.get("/forecast/latest")
    async def forecast_latest():
        async with get_session() as session:
            snap = (await session.execute(
                select(ForecastSnapshot).order_by(ForecastSnapshot.snapshot_date.desc())
            )).scalars().first()
            if snap is None:
                return {"snapshot": None, "outlook": []}
            forecasts = (await session.execute(
                select(TournamentForecast)
                .where(TournamentForecast.snapshot_id == snap.id)
                .order_by(TournamentForecast.p_champion.desc())
            )).scalars().all()
            teams_by_id = {
                t.id: t for t in (await session.execute(select(Team))).scalars().all()
            }
            return {
                "snapshot": {
                    "id": snap.id,
                    "snapshot_date": snap.snapshot_date.isoformat(),
                    "trigger": snap.snapshot_trigger,
                    "model_version": snap.model_version,
                },
                "outlook": [
                    {
                        "team": teams_by_id[f.team_id].name,
                        "p_champion": f.p_champion,
                        "poly_p_champion": f.poly_p_champion,
                        "edge_vs_poly": f.edge_vs_poly,
                    }
                    for f in forecasts
                ],
            }

    return app


# Module-level `app` for `uvicorn worldcap.api.app:app`. Skipped when tests / alembic
# import the module — controlled by WORLDCAP_SKIP_DEFAULT_APP (set in tests/conftest.py
# and migrations/env.py if needed).
if os.environ.get("WORLDCAP_SKIP_DEFAULT_APP") == "1":
    app = None
else:
    try:
        app = build_app()
    except Exception:  # noqa: BLE001 — don't crash imports if creds missing
        app = None
```

- [ ] **Step 5: Overwrite `tests/conftest.py` with the final content**

The conftest accumulates across tasks; this is the final version expected at this point:

```python
import os

# Skip building the real app on module import (no credentials in tests).
os.environ["WORLDCAP_SKIP_DEFAULT_APP"] = "1"

from pathlib import Path

import pytest
import respx


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    db_path = tmp_path / "worldcap.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(output_dir / "latest.md"))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
```

- [ ] **Step 6: Run test (expect pass)**

Run: `uv run pytest tests/test_app.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/worldcap/api/ tests/test_app.py tests/conftest.py
git commit -m "feat: FastAPI app with /healthz, /refresh, /forecast/latest"
```

---

## Task 18: End-to-end smoke run

**Files:**
- Modify: `README.md` (add a "smoke run" section showing the manual end-to-end)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Apply migrations against a fresh DB**

```bash
rm -f worldcap.db
uv run alembic upgrade head
uv run python scripts/seed_competition.py
```

Expected: `worldcap.db` exists with all 7 tables; competition row inserted.

- [ ] **Step 3: Start uvicorn**

```bash
uv run uvicorn worldcap.api.app:app --port 8765 &
sleep 2
curl -s http://localhost:8765/healthz
```

Expected: `{"status":"ok"}`.

Note: `/refresh` requires a valid `FOOTBALL_DATA_API_KEY`. If you don't have one yet, skip the live call — the test suite already validates the wiring with fakes.

- [ ] **Step 4: Stop the server**

```bash
kill %1
```

- [ ] **Step 5: Append smoke section to `README.md`**

```markdown

## Smoke run

    rm -f worldcap.db
    uv run alembic upgrade head
    uv run python scripts/seed_competition.py
    uv run uvicorn worldcap.api.app:app --port 8765
    # in another shell:
    curl -s http://localhost:8765/healthz
    curl -s -X POST http://localhost:8765/refresh
    cat output/$(date -u +%Y-%m-%d).md
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: smoke-run instructions"
```

---

## Verification checklist (end of Plan 1)

- [ ] `uv run pytest -v` passes all tests
- [ ] `uv run alembic upgrade head` applies cleanly from empty DB
- [ ] `scripts/seed_competition.py` is idempotent
- [ ] `uv run uvicorn worldcap.api.app:app` starts without errors
- [ ] `GET /healthz` returns `200 {"status": "ok"}`
- [ ] `POST /refresh` (with valid `FOOTBALL_DATA_API_KEY`) writes a digest to `output/YYYY-MM-DD.md` and updates `output/latest.md`
- [ ] APScheduler registers a `daily_refresh` job on startup

## What is NOT in this plan

These land in subsequent plans:

- Elo / match-level model (Plan 2)
- Monte Carlo simulator + tournament outlook with real champion/runner-up/semi probabilities (Plan 3)
- News / Reddit / Twitter ingest + sentiment scoring + Claude-written rationales (Plan 4)
- Top-scorer model + Golden Boot section in digest (Plan 5)
- HTMX dashboard + MCP exposure + production deploy (Plan 6)
- Post-match trigger (lands with results ingest in Plan 2)
