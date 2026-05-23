# worldcap

World Cup 2026 pre-match forecast feed. See `docs/specs/2026-05-21-worldcap-design.md`.

## Quick start

    uv sync
    cp .env.example .env  # fill in FOOTBALL_DATA_API_KEY
    uv run alembic upgrade head
    uv run python scripts/seed_competition.py
    uv run uvicorn worldcap.api.app:app --reload

## Smoke run

    rm -f worldcap.db
    uv run alembic upgrade head
    uv run python scripts/seed_competition.py
    uv run uvicorn worldcap.api.app:app --port 8765
    # in another shell:
    curl -s http://localhost:8765/healthz
    curl -s -X POST http://localhost:8765/refresh
    cat output/$(date -u +%Y-%m-%d).md

## Plan 2: Elo + per-match forecasts

The daily refresh pipeline now does:

1. Ingest fixtures + teams from football-data.org
2. Detect matches that flipped to FT (full time)
3. Seed any new teams with an initial Elo rating (from `data/fifa_ratings_seed.csv`)
4. Apply Elo updates from any newly-completed matches
5. Snapshot Polymarket WC 2026 outright winner odds
6. Generate a tournament-outlook forecast (Polymarket-as-forecast for now)
7. Generate per-match forecasts for the next 14 days (Elo-based)
8. Render the daily Markdown digest with both tournament outlook and per-match cards
9. Write to `output/YYYY-MM-DD.md` + the WhatsApp pickup file

The post-match scheduler runs every 5 minutes alongside the daily cron job.

### Initial team ratings

`data/fifa_ratings_seed.csv` ships with approximate Elo ratings (mean 1500, top
teams ~1900) keyed by country TLA. Edit the CSV directly to tune priors. Teams
present in the DB but missing from the CSV default to 1500.

## Plan 3: Monte Carlo simulator

The tournament outlook in the daily digest is now produced by a Monte Carlo
simulator that runs the rest of the World Cup 2,000 times every refresh
(target: 10,000 in production). For each iteration it:

1. Plays all 12 groups using the Plan 2 Elo-based match model
2. Resolves group standings via FIFA tiebreakers (points → GD → goals for → lots)
3. Seeds the 32-team knockout bracket from group standings + 8 best 3rd-placed
4. Plays R32 → R16 → QF → SF → F
5. Records the champion, runner-up, semifinalists, and group winners

Aggregated across iterations, this gives per-team probabilities for winning
the cup, reaching the semifinal, topping the group, etc. The digest's
"Tournament outlook" table now shows these model-derived numbers; the `Edge`
column shows where our model diverges from Polymarket's outright winner market.

The simulator is deterministic under a seed — set `WORLDCAP_SIMULATOR_SEED` if
you need reproducible runs (not currently wired through; pass `seed=` directly
to `generate_simulated_forecast` for now).
