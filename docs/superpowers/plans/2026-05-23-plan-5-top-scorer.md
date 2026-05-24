# worldcup — Plan 5: Top-scorer (Golden Boot) model

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Produce per-player Golden Boot probabilities alongside the existing tournament/per-match forecasts. Same simulator runs N=2,000 tournaments, and inside each tournament every watchlist player's total goals are sampled from a Poisson rate tied to their team's expected matches played. Aggregated: `p_golden_boot[player] = wins / N`. Blend with Polymarket top-scorer market when available.

**Architecture:**
- A `Player` table + a CSV seed (analogous to FIFA ratings) since the football-data.org free tier doesn't reliably expose player rosters
- Extend `SimulationResult` to track per-team "rounds reached" so we can derive expected matches per player from the same simulation that already runs
- New `simulator/top_scorer.py` — given per-team rounds and player rates, sample per-iteration Golden Boot winner
- `model/top_scorer_forecast.py` — orchestrates + persists `TopScorerForecast` rows
- Polymarket top-scorer market ingest (extends existing `ingest/polymarket.py`)
- Digest template adds a "Golden Boot race" section

**Tech stack:** No new dependencies.

**Plan sequence:**
- Plans 1–4 ✅
- Plan 5 (this) — top-scorer model
- Plan 6 — HTMX dashboard + MCP exposure + Hetzner deploy

---

## What changes for the user

The daily digest gains a new section:

```markdown
## Golden Boot race

| # | Player | P(top scorer) | Polymarket | Edge | Notes |
|---|--------|---------------|------------|------|-------|
| 1 | Mbappé      | 18% | 16% | +2pp | 0.71 g/90, France reaches SF in 38% of sims |
| 2 | Vinicius Jr.| 14% | 17% | -3pp | 0.65 g/90 |
| 3 | Haaland     | 11% | 10% | +1pp | 0.78 g/90 |
| ... |          |     |     |      |       |
```

---

## Domain model additions

Two new tables + a few constants. One migration `0008_top_scorer.py`.

```python
Player
  id, external_id (nullable, since seed source is CSV not API),
  name, team_id (FK), position (nullable),
  goals_per_90 (float),
  is_watchlist (bool, default True)

TopScorerForecast
  id, snapshot_id, player_id,
  p_golden_boot,
  expected_goals,
  poly_p_top_scorer (nullable),
  edge_vs_poly,
  model_version
```

`MatchEvent` (already exists from Plan 2) is not populated by Plan 5; goal attribution from real matches is deferred. Plan 5 produces forecasts from pre-tournament rates only.

## File structure

```
src/worldcup/
├── models/
│   ├── players.py             # NEW — Player
│   └── forecast.py            # add TopScorerForecast
├── ingest/
│   ├── players.py             # NEW — load watchlist from CSV
│   └── polymarket.py          # extend — top-scorer market
├── model/
│   ├── simulator/
│   │   ├── orchestrator.py    # extend — track per-team rounds reached
│   │   └── top_scorer.py      # NEW — per-iteration Golden Boot winner
│   └── top_scorer_forecast.py # NEW — persist TopScorerForecast rows
├── jobs/
│   └── refresh.py             # add players ingest + top-scorer steps
└── render/
    └── templates/
        └── digest_pretournament.md.j2  # Golden Boot race section

data/
└── players_seed.csv           # NEW

migrations/versions/
└── 0008_top_scorer.py
```

## Tasks

### Task 0: Schema (Player + TopScorerForecast + migration 0008)

- New `models/players.py` defining `Player`
- Add `TopScorerForecast` to `models/forecast.py`
- Register both in `models/__init__.py`
- Generate migration `0008_top_scorer.py`, rename, set rev/down_rev
- Apply against clean DB; verify new tables
- 96/96 tests still pass

### Task 1: Players seed CSV

- Create `data/players_seed.csv` with columns: `player_name, country_code, position, goals_per_90`
- Seed ~40 watchlist players (top scorers from major teams; goals_per_90 estimates from career stats — illustrative defaults)
- Create `ingest/players.py: load_seed_players(path=...)` — upserts Player rows by `(name, country_code)`. Idempotent.
- Test: seed 3 players, run twice, verify 3 rows + no duplicates

### Task 2: Simulator tracks per-team rounds reached

- Extend `SimulationResult` with a `team_round_counts: dict[Team, dict[str, int]]` where the inner dict counts how many iterations the team reached each round (`"group"`, `"R32"`, `"R16"`, `"QF"`, `"SF"`, `"F"`, `"champion"`)
- Update the orchestrator to populate this each iteration
- Add helper `expected_matches_played(team) -> float` that returns the mean number of matches the team plays across iterations (group teams always play 3; each round survived adds 1)
- Tests for: dominant team has expected_matches ≈ 7; cellar team ≈ 3

### Task 3: Top-scorer simulator

- `simulator/top_scorer.py: simulate_top_scorer_iteration(players_by_team, team_rounds_this_iter, rng) -> Player | None`
- For each player, sample `goals = Poisson(player.goals_per_90 × matches_played × start_prob)` where `start_prob=0.8` as a placeholder (Plan 5 doesn't model lineups; refine in v1)
- Return the player with highest goal total (ties broken by random lots via the same `rng`)
- Update orchestrator to call this per iteration and aggregate `top_scorer_counts: Counter[Player]`
- Expose `p_top_scorer(player)` and `expected_goals(player)` on `SimulationResult`
- Tests: dominant scorer (g/90 = 1.0) on a champion-bound team should top race in > 50% of iterations vs a 0.2 g/90 player on a group-only team

### Task 4: Top-scorer Polymarket ingest

- Extend `ingest/polymarket.py` with `ingest_top_scorer_market(collector)` — find the market whose question contains `"top scorer"` or `"golden boot"` and `"world cup 2026"`, persist as `OddsSnapshot(market_type="top_scorer", outcomes={player_name: prob, ...})`
- Test with mocked collector returning a curated top-scorer market

### Task 5: Top-scorer forecast generator

- `model/top_scorer_forecast.py: generate_top_scorer_forecast(simulation_result, snapshot_id)`:
  - For each watchlist player: read `p_top_scorer(player)` and `expected_goals(player)` from the sim
  - Look up matching `poly_p` from the latest top-scorer `OddsSnapshot` (by exact name)
  - Compute `edge_vs_poly = p_top_scorer − poly_p` (or 0 if no market entry)
  - Write `TopScorerForecast` rows linked to the given `snapshot_id`
- Tests asserting row counts, sum constraint (≈1.0 across watchlist with caveat that non-watchlist players are aggregated as residual), edge calc

### Task 6: Wire into `run_refresh`

- After `generate_simulated_forecast` produces a snapshot, call:
  - `load_seed_players()` (idempotent; Plan 5 calls every refresh)
  - `generate_top_scorer_forecast(sim_result, snap.id)` — but the current `generate_simulated_forecast` doesn't return the `SimulationResult`. **Refactor** it to return both `(snapshot, sim_result)` so callers can reuse the simulation.
- Add `ingest_top_scorer_market(poly_collector)` before forecast generation (similar to the existing outright-winner step)

### Task 7: Render Golden Boot section

- Extend `render/markdown.py` with a query for top-N `TopScorerForecast` rows + a `TopScorerRow` dataclass
- Add a "Golden Boot race" section to the digest template between "Tournament outlook" and "Per-match forecasts"

### Task 8: Smoke + README

- Full-WC integration test: extend the existing rationale-test to also seed players, run refresh, assert `TopScorerForecast` rows exist + at least one has `p_golden_boot > 0`
- README: add Plan 5 section explaining the model + the players seed CSV

## Acceptance for Plan 5

- All previous tests still pass (96/96)
- After a `run_refresh`, `TopScorerForecast` rows are written for every seeded watchlist player
- Sum of `p_golden_boot` across all watchlist players is in [0, 1] (residual = chance non-watchlist player wins; we don't model the long tail explicitly)
- A dominant scorer test produces > 50% Golden Boot probability
- Daily digest renders a "Golden Boot race" section showing the top 10 candidates with model prob, Polymarket prob, and edge
