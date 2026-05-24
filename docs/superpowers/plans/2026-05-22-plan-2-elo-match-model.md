# worldcup — Plan 2: Results ingest + Elo + match model

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Replace Plan 1's "Polymarket-as-forecast" with a real per-match forecast: Elo-derived `(p_home, p_draw, p_away)` for every fixture-known match, blended with Polymarket per-match odds when available. Ingest completed-match results, update Elo from results, persist `MatchForecast` rows, and surface them in the daily digest.

**Architecture:** New module `model/elo.py` holds rating logic; `model/match.py` produces per-match probabilities. `ingest/results.py` polls the sports-data API for matches that have flipped to FT, persists scores + `MatchEvent` rows. `jobs/refresh.py` calls Elo updates after results land. The digest template grows a "Per-match forecasts" section.

**Tech stack:** No new dependencies. Uses existing httpx, SQLModel, jinja2, APScheduler.

**Plan sequence (context):**
- Plan 1 ✅ — foundations + thin pipeline
- Plan 2 (this) — results ingest + Elo + match model
- Plan 3 — Monte Carlo simulator + tournament outlook (replaces Plan 1's Polymarket-as-forecast for tournament probs)
- Plan 4 — news/Reddit ingest + Claude rationales
- Plan 5 — top-scorer model
- Plan 6 — dashboard + MCP + deploy

---

## Cleanup carried from Plan 1 final review

These are folded into **Task 0** (a single cleanup commit) before any new feature work:

- Move `get_settings.cache_clear()` + `reset_engine_cache()` into the `_isolated_env` autouse fixture (eliminates 30+ duplicated calls across test files).
- Add `competition_id: int` parameter to `run_refresh` (defaults to looking up `settings.db_competition_code`, so existing callers are unchanged).
- Rename `ForecastSnapshot.state_hash` → `poly_odds_hash` (the column currently only hashes Polymarket odds; will be revisited in Plan 2 once Elo state enters the forecast). Migration: `0003_rename_state_hash.py`.

---

## File structure created in this plan

```
src/worldcup/
├── models/
│   ├── tournament.py        # add MatchEvent
│   └── forecast.py          # add MatchForecast; field rename in ForecastSnapshot
├── ingest/
│   └── results.py           # NEW — ingest FT matches + goals
├── model/
│   ├── elo.py               # NEW — Elo rating + K-factor + update
│   ├── match.py             # NEW — produces (p_home, p_draw, p_away)
│   └── ratings.py           # NEW — load/persist team ratings (TeamRating table)
├── jobs/
│   └── refresh.py           # extend pipeline: results -> elo update -> match forecasts
└── render/
    └── templates/
        └── digest_pretournament.md.j2  # add per-match forecast cards

data/
└── fifa_ratings_seed.csv    # NEW — initial team ratings seed

migrations/versions/
├── 0003_rename_state_hash.py        # NEW (Task 0)
├── 0004_match_event_team_rating.py  # NEW (Tasks 1+2)
└── 0005_match_forecast.py           # NEW (Task 7)
```

## Tasks

Each task ships as one commit. TDD discipline: failing test → minimal implementation → passing test → commit. Subagents receive the full code in their dispatch prompts (not by reading this file).

### Task 0: Plan 1 cleanups
- Move cache-reset calls into autouse fixture
- Add `competition_id` to `run_refresh` (with default lookup)
- Rename `state_hash` → `poly_odds_hash` via migration `0003`
- Run full suite; confirm 21/21 still passing

### Task 1: MatchEvent model + migration
- `MatchEvent(id, match_id, ts_minute, type, player_external_id, detail_json)` — `type ∈ {goal, own_goal, assist, red_card, yellow_card}`
- Migration `0004` (created together with Task 2's TeamRating)

### Task 2: TeamRating model + migration
- `TeamRating(id, team_id, rating, last_updated, source)` — `source ∈ {seed, in_tournament}`
- Migration `0004` (combined with Task 1)

### Task 3: Sports-data results ingest
- `FootballDataClient.get_match_events(external_id)` — pull events for a specific FT match
- `ingest/results.py: ingest_completed_results(client)` — pull all WC matches, find ones whose status flipped to FT since last run, persist scores + MatchEvent rows
- Idempotent: rerun produces no extra rows

### Task 4: Elo module
- `model/elo.py`:
  - `INITIAL_RATING = 1500.0`, `K_BASE = 32.0`
  - `expected_score(home_r, away_r) -> float` — standard Elo formula with 100-pt home advantage
  - `k_factor(stage: str) -> float` — `group=32`, `R32=48`, `R16=56`, `QF=64`, `SF=72`, `F=80`
  - `update_ratings(home_r, away_r, result, stage) -> tuple[float, float]` — `result ∈ {1.0 (home win), 0.5 (draw), 0.0 (away win)}`

### Task 5: FIFA ratings seed
- `data/fifa_ratings_seed.csv` with one row per WC 2026 team (placeholder values; real data fetched separately)
- `model/ratings.py: load_seed_ratings()` — reads CSV, upserts into TeamRating with `source='seed'`
- Called once from `scripts/seed_competition.py` after teams are ingested

### Task 6: Match model
- `model/match.py`:
  - `match_probabilities(home_rating, away_rating, *, draw_pct: float = 0.27) -> dict[str, float]` — derive `(p_home, p_draw, p_away)` from Elo using a fixed draw bucket. `draw_pct` is the empirical WC draw rate (~27%); split remaining mass proportionally to Elo expected scores.
  - `blend_with_market(model_p: dict, market_p: dict | None, *, alpha: float = 0.3) -> dict` — weighted blend; falls back to `model_p` when market is None.

### Task 7: MatchForecast model + migration
- `MatchForecast(id, snapshot_id, match_id, p_home, p_draw, p_away, p_home_poly, p_draw_poly, p_away_poly, edge_vs_poly, model_version)`
- Migration `0005`

### Task 8: Per-match forecast generator
- `model/per_match.py: generate_match_forecasts(snapshot_id, as_of, horizon_days=14)`:
  - Pulls fixtures with both teams resolved and kickoff in `[as_of, as_of+horizon_days]`
  - For each: looks up team ratings, calls `match_probabilities`, looks up any per-match Polymarket odds (none in Plan 2, but interface ready), blends
  - Writes `MatchForecast` rows linked to the snapshot

### Task 9: Wire into `run_refresh`
- Pipeline order: ingest fixtures → ingest results → update Elo from new results → ingest Polymarket outright → naive (tournament) forecast → per-match forecasts → render → write
- `_state_hash` (now `poly_odds_hash`) stays Polymarket-only; Plan 3 will add a sibling hash for model state.

### Task 10: Template updates
- Add a "Per-match forecasts (next 14 days)" section between "Tournament outlook" and "Next matches"
- Each card: matchup, our probabilities, Polymarket (or "—" if absent), edge (or "—")

### Task 11: Post-match scheduler trigger
- New cron-style job: every 5 minutes, check if any match is in `LIVE` or recently flipped to `FT`. If yes, enqueue a refresh.
- Wired into `build_scheduler` alongside the daily job.
- Test: scheduler now has 2 jobs registered (`daily_refresh` + `post_match_check`).

### Task 12: End-to-end smoke
- Integration test extending `test_refresh.py`: seeds ratings, ingests a fixture with kickoff in 7 days, asserts a `MatchForecast` row is written and the digest contains the per-match section.
- README addition: explain the FIFA ratings seed step + how to refresh it.

## Acceptance for Plan 2

- 21/21 (from Plan 1) + new tests all passing
- `MatchForecast` row exists for every fixture-known match within the 14-day horizon after a refresh
- Elo ratings persist; after a fake "Brazil beats France 2-0 in group stage" result, Brazil's rating increases and France's decreases by symmetric amounts (K=32)
- Daily digest includes a "Per-match forecasts" section in pre-tournament mode
- Scheduler registers both daily and post-match jobs
