# worldcup — Plan 3: Monte Carlo tournament simulator

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Replace Plan 1's "Polymarket-as-tournament-forecast" with a real Monte Carlo simulator. Given the match model (from Plan 2), simulate the rest of the tournament N=10,000 times, aggregate per-team championship/runner-up/semi/top-of-group probabilities, persist as `TournamentForecast` rows.

**Architecture:** New `model/simulator/` subpackage with three pure-functional layers:
- `tiebreakers.py` — implement FIFA group tiebreaker rules
- `group_stage.py` — simulate one group → ordered standings
- `bracket.py` — simulate the knockout bracket from standings
- `run.py` — orchestrate N iterations, aggregate

The simulator is **deterministic given a seed** — same seed produces identical results, so tests can assert exact probabilities.

**Tech stack:** No new dependencies. Pure Python stdlib (`random`).

**Plan sequence:**
- Plan 1 ✅ — foundations + thin pipeline
- Plan 2 ✅ — results ingest + Elo + per-match forecasts
- Plan 3 (this) — Monte Carlo simulator + real tournament outlook
- Plan 4 — news/Reddit ingest + Claude rationales
- Plan 5 — top-scorer model (leans on this simulator's player-minutes outputs)
- Plan 6 — dashboard + MCP + deploy

---

## What changes for the user

Before Plan 3:
- Tournament outlook = Polymarket-as-forecast (raw Polymarket champion probabilities, with `edge_vs_poly = 0` by construction)

After Plan 3:
- Tournament outlook = our model's championship probabilities (derived from Elo + simulator)
- `p_runner_up`, `p_semi`, `p_top_group` populated honestly per team
- `edge_vs_poly = our_p_champion − polymarket_p_champion` — surface where we diverge from the market

---

## Domain model additions

No new tables in Plan 3. Existing `TournamentForecast` (created in Plan 1) already has the right columns; we just start populating `p_runner_up`, `p_semi`, `p_top_group` (currently default 0.0).

Two minor additions to existing tables:

- `ForecastSnapshot` gets a sibling hash for the model state: add `model_state_hash: Optional[str]`. Plan 1's `poly_odds_hash` stays; Plan 3 adds `model_state_hash` covering team Elo ratings. Migration `0006_model_state_hash.py`.
- `Match.bracket_slot: Optional[str]` — encodes which slot a knockout match represents (e.g. `"R32-1"`, `"R32-2"`, ..., `"F"`). Filled when football-data.org returns concrete knockout fixtures, but used by the simulator as a fallback when fixtures aren't known yet. Migration `0007_match_bracket_slot.py`.

## WC 2026 format reminder

- 48 teams · 12 groups of 4
- Top 2 from each group (24 teams) + 8 best 3rd-placed teams = 32 to knockout
- Single elimination: R32 → R16 → QF → SF → F (plus 3rd-place playoff)

Group tiebreaker order (FIFA-published):
1. Points
2. Goal difference across all group matches
3. Goals scored across all group matches
4. Head-to-head points among tied teams
5. Head-to-head goal difference among tied teams
6. Head-to-head goals scored among tied teams
7. Fewer disciplinary points (Fair Play)
8. Drawing of lots

For Plan 3 v0 we implement 1–3 and 8 (lots, deterministic from RNG). 4–6 (head-to-head) and 7 (fair play) are deferred — they affect a small minority of tied-on-points scenarios. Note this explicitly in the code.

---

## File structure created in this plan

```
src/worldcup/
├── models/
│   ├── tournament.py        # add Match.bracket_slot
│   └── forecast.py          # add ForecastSnapshot.model_state_hash
├── model/
│   ├── simulator/
│   │   ├── __init__.py
│   │   ├── score_sampling.py    # 3-way outcome + score sampler
│   │   ├── tiebreakers.py       # WC group tiebreakers
│   │   ├── group_stage.py       # simulate one group
│   │   ├── bracket.py           # simulate knockout
│   │   ├── orchestrator.py      # run N iterations, aggregate
│   │   └── bracket_template.py  # WC26 slot mappings (12 groups → R32 → ... → F)
│   └── simulated_forecast.py    # replaces naive.py role; uses simulator
└── jobs/
    └── refresh.py               # swap naive → simulated forecast generator

migrations/versions/
├── 0006_model_state_hash.py
└── 0007_match_bracket_slot.py
```

`model/naive.py` is preserved for now but no longer called from `run_refresh`. (Plan 4 may delete it; for Plan 3 we keep it as a reference implementation and the existing tests stay green.)

## Tasks

Each task ships as one commit. TDD for the pure modules; integration test at the end.

### Task 0: Schema additions (migrations 0006 + 0007)

- Add `ForecastSnapshot.model_state_hash: Optional[str]`
- Add `Match.bracket_slot: Optional[str]`
- Generate one combined migration `0006_simulator_schema.py`
- Confirm `alembic upgrade head` from fresh DB still produces all tables + new columns
- Full suite still 45/45 passing

### Task 1: Score sampling

`model/simulator/score_sampling.py`:
- `sample_outcome(p_home, p_draw, p_away, rng) -> str` — returns `"home" | "draw" | "away"` using one `rng.random()` draw
- `sample_score(outcome, home_strength, away_strength, rng) -> tuple[int, int]` — given an outcome, sample a plausible scoreline. v0 implementation: Poisson with rates derived from team strengths and outcome bias. The function is *not* required to be statistically realistic at v0 — it just needs to produce integer goals consistent with the outcome (winner's score > loser's, equal for draws). Tested for invariants only.

### Task 2: Tiebreakers

`model/simulator/tiebreakers.py`:
- Function `resolve_standings(matches: list[GroupMatch], rng) -> list[Team]` returning 4 teams in finishing order
- Implement steps 1, 2, 3, 8 (lots) from FIFA's published order. Steps 4–7 deferred; document inline.
- Unit tests:
  - Clean case (no ties) — straightforward ranking
  - Tied on points → GD breaks it
  - Tied on points + GD → GF breaks it
  - Tied on everything → deterministic lots (seeded RNG)

### Task 3: Group stage simulator

`model/simulator/group_stage.py`:
- `simulate_group(teams, ratings_by_team, rng) -> list[Team]` — plays all 6 matches in a 4-team group using `match_probabilities` + `sample_outcome` + `sample_score`, then calls `resolve_standings`
- Returns the 4 teams in finishing order
- Test: with a clearly dominant team (rating 1900 vs three 1300s), it tops the group ≥ 95% of 1000 trials

### Task 4: Bracket template + knockout simulator

`model/simulator/bracket_template.py`:
- A constant `WC2026_BRACKET: list[BracketSlot]` describing how group standings feed into the 16 R32 matches
- For v0 use a simplified "1st of A vs best-3rd, 1st of B vs 2nd of C, ..." mapping. The exact FIFA template can be refined later.
- 8 best 3rd-placed teams chosen by points → GD → GF across all groups

`model/simulator/bracket.py`:
- `simulate_knockout(seeded_teams: list[Team], ratings_by_team, rng) -> dict` — plays R32, R16, QF, SF, F
- Returns `{"champion": Team, "runner_up": Team, "semifinalists": list[Team]}`
- v0: knockout matches use `match_probabilities` with `home_advantage=0` (neutral venues from QF onward at WC; for simplicity treat all knockouts as neutral). On a draw, coin-flip the advancer.

### Task 5: Orchestrator

`model/simulator/orchestrator.py`:
- `simulate_tournament(groups, ratings_by_team, n_iterations=10_000, seed=None) -> SimulationResult` where `SimulationResult` is a dataclass aggregating per-team counts and helpers like `p_champion(team)`, `p_semi(team)`, `p_top_group(team)`.
- Performance target: 10,000 iterations × 12 groups × 6 matches + 31 knockout matches ≈ 1M `random.random()` calls + some sorting. Should run in well under 5 seconds in CPython.

### Task 6: Simulated forecast generator

`model/simulated_forecast.py`:
- `generate_simulated_forecast(trigger, n_iterations=10_000, seed=None) -> ForecastSnapshot`
- Loads competition + teams + ratings + group definitions + latest Polymarket outright snapshot
- Calls `simulate_tournament(...)`
- Writes `ForecastSnapshot` (with `model_state_hash` = hash of ratings + `poly_odds_hash` = hash of Polymarket outcomes) and `TournamentForecast` rows with `p_champion / p_runner_up / p_semi / p_top_group` populated.
- For `edge_vs_poly`: subtract Polymarket implied prob (when available for that team in the outright market) from our `p_champion`.

### Task 7: Wire into refresh

In `jobs/refresh.py`:
- Replace `generate_naive_forecast(trigger=trigger)` with `generate_simulated_forecast(trigger=trigger)`
- The downstream `generate_match_forecasts` call is unchanged.
- The naive forecast generator stays in the codebase (and its tests stay) — it's just no longer wired in.

### Task 8: Update integration test + smoke

- Extend `tests/test_refresh.py` to seed all 48 WC2026 teams + ratings + group fixtures and assert:
  - `TournamentForecast` rows exist for every team
  - Sum of `p_champion` across teams ≈ 1.0 (Monte Carlo noise: ±0.5pp)
  - At least one team has `p_semi > 0`
- README: add a short Plan 3 section explaining the simulator + the `edge_vs_poly` interpretation.

## Acceptance for Plan 3

- All previous tests still pass (45/45)
- New simulator tests pass
- A `run_refresh` against the seeded WC2026 produces `TournamentForecast` rows whose `p_champion` values sum to 1 ± 0.005
- For a clearly dominant test setup (one team rated 1900, rest at 1300), that team's simulated `p_champion` is > 50%
- Daily digest's "Tournament outlook" table now reflects model probabilities, with non-zero `edge_vs_poly` columns when teams' p_champion differs from Polymarket
