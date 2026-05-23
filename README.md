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

## Plan 4: News, sentiment, and Claude rationales

The daily refresh now produces a 2-3 sentence written rationale for each
fixture-known match, persisted as `MatchForecast.rationale_md` and surfaced in
the digest below each per-match card.

The pipeline added four new stages between Elo updates and forecast generation:

1. **News ingest** (GNews via the `connectors` library) — per-team queries write
   `NewsItem` rows, idempotent on URL.
2. **Reddit ingest** — pulls recent posts from `r/soccer`, `r/worldcup`,
   `r/footballtactics`, tags each post to a team when a team name appears in the
   text.
3. **Sentiment scoring** — Claude (cheap model, `claude-haiku-4-5` by default)
   scores each new post + news item; results land in `SentimentScore` rows.
4. **Team rollups** — confidence-weighted mean of recent post/news scores per
   team, written as a `target_type="team"` `SentimentScore` row.

After per-match forecasts are written, a final stage loops them and calls Claude
(smart model, `claude-sonnet-4-5` by default) with a structured prompt
containing team form, Elo ratings, our 3-way probability, Polymarket prob,
edge, recent headlines, and the sentiment summary. A per-refresh token budget
(`RATIONALE_TOKEN_BUDGET`, default 100,000) caps spend; on overrun the loop
logs and stops cleanly.

### Required env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Claude SDK key |
| `GNEWS_API_KEY` | — | GNews API key |
| `REDDIT_CLIENT_ID` | — | Reddit API client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit API client secret |
| `REDDIT_USER_AGENT` | `worldcap/0.1` | Reddit API user agent |
| `SENTIMENT_MODEL` | `claude-haiku-4-5` | Model used for batch sentiment |
| `RATIONALE_MODEL` | `claude-sonnet-4-5` | Model used for per-match rationale |
| `RATIONALE_TOKEN_BUDGET` | `100000` | Per-refresh cap on rationale tokens |

When `ANTHROPIC_API_KEY` is empty, sentiment scoring and rationale generation
are **skipped with a warning** (graceful degradation); the rest of the pipeline
still runs end-to-end.

## Plan 5: Top-scorer (Golden Boot) model

The simulator now also produces per-player Golden Boot probabilities. For each
of the 2,000 simulated tournaments (per refresh), every watchlist player's
tournament-total goals are sampled from
`Poisson(goals_per_90 × matches_played × start_prob)`, where
`matches_played` comes from how far their team advanced in that specific
iteration and `start_prob` defaults to 0.8 (refining lineups is a v1 concern).
The player with the highest sampled total wins the iteration; aggregated across
iterations, this gives `p_golden_boot` per player.

### Watchlist

`data/players_seed.csv` ships with approximate `goals_per_90` rates for ~40
candidate scorers, keyed by TLA. Edit it to tune priors or add players. Teams
whose country code isn't present in the seed have no watchlist entries (so
non-watchlist players are implicitly ignored — a known v0 simplification).

### Output

The digest now includes a "Golden Boot race" section ranking the top 10
candidates with our probability, Polymarket's top-scorer market (when
available), and the edge.
