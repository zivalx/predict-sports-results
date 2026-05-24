# worldcup — Design Spec

**Date:** 2026-05-21
**Status:** Draft for review
**Scope:** World Cup 2026 only (single tournament). Designed with clean seams so future tournaments / sports can be added without rewriting, but no generalization implemented in v0.

## 1. Purpose

Produce a daily pre-match forecast feed for the FIFA World Cup 2026, covering:

1. **Per-match outcome probabilities** for every fixture whose teams are currently known.
2. **Tournament-level probabilities** per team (champion, runner-up, semifinal appearance, top of group).
3. **Top-scorer probabilities** per player (Golden Boot race).

The system starts producing forecasts **as soon as it is deployed** — meaningfully ahead of the tournament (target: ~2 months before kickoff). Forecasts refresh daily from that point on, plus an extra refresh after every completed match once the tournament begins. Output is a Markdown digest (picked up by the existing `whatsapp-daily-bot`) and a lightweight HTMX dashboard. The product surface is the *rationale* — calibrated probabilities plus a short Claude-written explanation, not raw numbers.

Polymarket is treated as the wisdom-of-crowds anchor; the model produces an independent estimate; the rationale surfaces where they diverge ("edge").

## 2. Non-goals (v0)

- In-match live updates (we are strictly pre-match / post-match)
- Per-event tracking (passes, possession, xT)
- Betting recommendations or stake sizing
- Generalization to other tournaments or sports (kept as clean seams only)
- Calibration of model weights from prior tournaments — start with sensible priors, recalibrate after group stage
- Snapshot-delta UI in the daily digest (storage of snapshots is kept for retro-calibration; visual day-over-day deltas are deferred)

## 2.1 Lifecycle phases

The system runs continuously across four phases. The pipeline is the same; what differs is which sections of the daily output have content and which signals dominate.

| Phase | Window | What we have | What dominates the digest |
|---|---|---|---|
| **Pre-tournament** | T−2mo → T−1d | All 48 group fixtures known; no completed matches; Polymarket champion + top-scorer markets active; per-match Polymarket markets appear progressively; friendlies + squad news | Tournament outlook, Golden Boot race, "notable movers" driven by squad selection / injury news / friendly results |
| **Group stage** | T → T+~2wk | All 48 fixtures, results landing daily; knockout slots filling | Today's matches + tournament outlook (now constrained by partial standings) + Golden Boot |
| **Knockout** | T+~2wk → final | Fixed bracket, two matches per day tapering to one | Today's match (deep dive) + remaining tournament outlook + Golden Boot |
| **Post-tournament** | Final → T+1wk | Full results | Retro-calibration report; system can be shut down |

Pre-tournament is **not** an empty mode — it's where the tournament-outlook and top-scorer forecasts deliver almost all of the system's value. The first daily digest goes out the day the system is deployed, with "next matches" replacing "today's matches" until the tournament begins.

## 3. Architecture

Four-layer service, single Python process, single SQLite database to start.

```
                  ┌──────────────────────────────────┐
                  │      worldcup/  (new repo)       │
                  └──────────────────────────────────┘
                                  │
   ingest/   ──►   enrich/   ──►   model/   ──►   render/   ──►   api/
                                                                   │
                                                            (FastAPI + MCP)

   ingest/                          model/
   ├── fixtures (sports-data API)   ├── match_model    (Elo + Polymarket blend)
   ├── results                      ├── simulator      (Monte Carlo bracket, N=10k)
   ├── lineups                      └── topscorer      (xG + minutes + sim-conditional)
   ├── polymarket (collectors lib)
   │     ├── per-match markets
   │     ├── outright winner
   │     ├── stage advancement
   │     └── top scorer
   ├── news / reddit / twitter (collectors lib)
   └── player_stats (goals, minutes, xG)
```

### 3.1 Layers

- **ingest/** — Source adapters conforming to a single `Source` protocol (`fetch(window) -> list[Event]`). Polymarket, GNews, Reddit, Twitter use the existing `collectors` library directly. Fixtures, results, lineups, and player stats come from a sports-data API (football-data.org free tier for v0; the adapter interface lets us swap to API-Football / SportMonks later).
- **enrich/** — Sentiment scoring of news/social posts via the Claude SDK in batches; per-team and per-match aggregation; injury / lineup change detection.
- **model/** — Three modules: match-level outcome model, Monte Carlo tournament simulator, top-scorer model.
- **render/** — Produces the daily Markdown digest (one file per snapshot), refreshes the HTMX dashboard, writes the pickup file the WhatsApp bot reads.
- **api/** — FastAPI + auto-exposed MCP tools (`get_match_forecast`, `get_tournament_outlook`, `get_topscorer_race`).

### 3.2 Stack

- Python 3.12, FastAPI, async, Pydantic (matches `trender` so a future merge is trivial)
- SQLite v0 — single process, single host. Migrate to Postgres only if scale demands.
- APScheduler for daily + post-match triggers (single binary, no Celery)
- Claude SDK for sentiment and rationale generation (no FinBERT — fan/journalist sentiment is informal, not finance-tuned)
- Deploy: Hetzner VPS (per existing plan), `uv` + systemd

## 4. Domain model

Deliberately sport-agnostic naming. No table or column says "soccer".

```
Competition       (id, name, format_id, start_date, end_date)
TournamentFormat  (id, groups_n, group_size, knockout_size, tiebreaker_rules_json)
Team              (id, name, country_code, fifa_rank)
Player            (id, name, team_id, position, dob)

Match             (id, competition_id, stage, group_label,
                   home_team_id, away_team_id, kickoff_utc, status, final_score)
                   -- stage ∈ {group, R16, QF, SF, F, 3rd}

MatchEvent        (id, match_id, ts, type, player_id, detail)
                   -- type ∈ {goal, own_goal, assist, red_card, ...}

OddsSnapshot      (id, match_id|null, market_type, source='polymarket',
                   ts, outcomes_json, volume)
                   -- market_type ∈ {match_3way, outright_winner,
                                     stage_advancement, top_scorer}
                   -- outcomes_json shape varies by market_type:
                   --   match_3way:        {home: p, draw: p, away: p}
                   --   outright_winner:   {team_id: p, ...}
                   --   top_scorer:        {player_id: p, ...}
                   --   stage_advancement: {team_id: p, ...}

NewsItem          (id, match_id|null, team_id|null, source, url, ts,
                   title, summary)
SocialPost        (id, match_id|null, team_id|null, platform, ts, text,
                   author, engagement)
SentimentScore    (id, target_type, target_id, ts, score, confidence,
                   model_version)
                   -- target_type ∈ {team, match, player}

ForecastSnapshot   (id, snapshot_date, snapshot_trigger, state_hash, created_at)
                   -- trigger ∈ {daily, post_match, manual}
MatchForecast      (snapshot_id, match_id,
                    p_home, p_draw, p_away, edge_vs_poly, rationale_md)
TournamentForecast (snapshot_id, team_id,
                    p_champion, p_runner_up, p_semi, p_top_group)
TopScorerForecast  (snapshot_id, player_id,
                    p_golden_boot, expected_goals, edge_vs_poly)
```

Snapshots are persisted for every refresh. The v0 UI does not surface deltas, but retro-calibration of model weights against later results requires the historical record.

## 5. Match model

**v0 (ship first):** Elo-style team rating seeded from FIFA rankings and recent form, blended with Polymarket implied probabilities:

```
our_p = α · elo_p + (1 − α) · poly_p
```

with `α = 0.3` (we mostly trust the market but inject independent signal). The Elo rating updates after each completed match using standard Elo with a K-factor proportional to tournament stage.

**v1 (after group stage results land):** Add features for sentiment delta, key-player injury flags, rest days, travel distance. Use logistic regression with hand-set priors — *not* a deep model. Keep it interpretable so the rationale is honest.

Explicit non-goal: train an ML model from scratch. The product is a thoughtful daily forecast with rationale, not Kaggle.

## 6. Tournament simulator

Pure Monte Carlo. Inputs:

- Current standings + completed matches
- The match model (returns `P(outcome)` for any fixture, including hypothetical slot-known matches like "Winner of Group A vs Runner-up of Group B")

Algorithm:

1. For each of N = 10,000 iterations:
   - Simulate every remaining group-stage match by sampling from the match model
   - Resolve group standings using real WC tiebreakers (points → GD → GF → H2H → fair play → draw of lots), encoded as a single `resolve_group_standings(matches) -> List[Team]` function
   - Construct the knockout bracket from standings
   - Simulate each knockout tie. v0: sample 90-minute outcome; on draw, flip a coin for advancement (extra-time / penalty model deferred)
   - Record the champion, runner-up, semifinalists
2. Aggregate over iterations:
   - `championships[team] / N → p_champion`
   - `final_appearances[team] / N → p_finalist`; derive `p_runner_up = p_finalist − p_champion`
   - `semifinal_appearances[team] / N → p_semi`

Cost: ~10k iterations × O(matches per tournament) is sub-second in Python with vectorised numpy. Acceptable.

## 7. Top-scorer model

Hard to do well, easy to do reasonably. v0 approach:

- **Watchlist:** ~40 candidate players, drawn from Polymarket's listed top-scorer market plus each team's top scorer in qualifying. Keeps per-iteration cost cheap.
- **Per-candidate features:**
  - `goals_so_far` (observed from `MatchEvent`)
  - `expected_remaining_minutes` = Σ over future matches of `P(team_plays_match) × P(player_starts) × 90` — `P(team_plays_match)` comes from the simulator; `P(player_starts)` is a heuristic from recent lineup data (1.0 if started last match and not flagged injured, 0.5 if rotated, 0.0 if injured/suspended)
  - `goals_per_90` from pre-tournament + tournament data
  - `expected_goals_remaining ~ Poisson(goals_per_90 × minutes / 90)`
- **From features to probability:** Inside the simulator, sample each watchlist player's total tournament goals; the argmax across the watchlist is the simulated Golden Boot winner. `p_golden_boot[player] = wins[player] / N`.
- **Blend with Polymarket:** Same form as the match model — `our_p = α · sim_p + (1 − α) · poly_p`, with the same `α = 0.3`.

Anyone outside the watchlist is implicitly given `p_golden_boot ≈ 0`. We re-evaluate watchlist membership after every match day so a breakout scorer can be added.

## 8. Daily pipeline

A single batch job, idempotent, triggered by APScheduler.

```
Triggers:
  - Daily at 09:00 local (always run, every phase including pre-tournament)
  - Post-match: poll sports-data API every 5 min during match windows;
                when a match flips to FT, enqueue a refresh
                (group + knockout phases only)
  - Manual: POST /refresh
```

Steps:

1. **Refresh fixtures** — pull next 7 days from sports-data API
2. **Ingest completed results** — for any match that flipped to FT since last run, persist final score and `MatchEvent`s (goals, cards)
3. **Snapshot odds** — pull Polymarket match markets, outright winner market, stage-advancement markets, top-scorer market via `collectors`
4. **Ingest context** — last 72h of news + Reddit + (optional) Twitter, scoped per team and per active match
5. **Score sentiment** — Claude SDK batch over new posts; aggregate per team and per match
6. **Update Elo** — apply post-match Elo updates for any new results
7. **Generate match forecasts** — for every fixture-known match, compute `(p_home, p_draw, p_away)` and `edge_vs_poly`
8. **Run simulator** — N=10k iterations; produce tournament-level probabilities
9. **Run top-scorer model** — driven by the same simulator pass
10. **Write rationales** — Claude SDK call per fixture-known upcoming match and per "notable mover" (significant change vs Polymarket consensus); structured prompt with (form, odds, edge, top news headlines, sentiment summary) → 2–3 sentence rationale
11. **Persist** — write `ForecastSnapshot` and the three forecast tables
12. **Render** — regenerate the daily Markdown file at `output/YYYY-MM-DD.md`, refresh the dashboard, update the WhatsApp pickup file

Steps 1–6 are I/O bound and run concurrently where dependencies allow; step 8 is CPU-bound but small; step 10 is rate-limited by Claude API.

## 9. Daily output format

Pre-tournament digests replace the "Today's matches" section with "Next matches" (3 nearest fixtures with current Polymarket lines and any notable injury / lineup news per side). Group + knockout digests show today's fixtures as below.

```markdown
# World Cup — 2026-06-15  ·  Day 4 of group stage  (or "T−47 days" pre-tournament)

## Today's matches

### Brazil vs Switzerland · 21:00 UTC · Group G
**Our forecast:** Brazil 62% · Draw 24% · Switzerland 14%
**Polymarket:**  Brazil 68% · Draw 22% · Switzerland 10%
**Edge:** −6pp on Brazil (we're cooler than market)

Brazil's last two friendlies were unconvincing and Vinicius is doubtful;
market hasn't fully priced this in. Reddit sentiment around the squad has
softened over 48h. Still a clear favorite, but the price is short.

[3 news links] [2 reddit thread links]

[...one card per fixture-known match in the next 24h]

## Tournament outlook

| # | Team | Champion | Polymarket | Edge |
|---|------|----------|------------|------|
| 1 | Brazil    | 22% | 25% | −3pp |
| 2 | France    | 18% | 16% | +2pp |
| 3 | Argentina | 15% | 17% | −2pp |
[...top 10]

## Golden Boot race

| # | Player | P(top scorer) | Polymarket | Edge | Notes |
|---|--------|---------------|------------|------|-------|
| 1 | Mbappé       | 18% | 16% | +2pp | 4 goals, France finalist 38% in sim |
| 2 | Vinicius Jr. | 14% | 17% | −3pp | 3 goals, doubtful for next match  |
| 3 | Haaland      | 11% | 10% | +1pp |                                   |
[...top 10]
```

No day-over-day deltas in v0.

## 10. Future-generalization seams (built in, not implemented)

These boundaries exist so generalization is additive, not a rewrite:

- `Source` protocol — adding a new fixtures provider is one adapter
- `TournamentFormat` table — adding Euros 2028 / a league is an `INSERT`
- `target_type` discriminator on `SentimentScore` — already supports team / match / player
- 3-way odds schema generalizes to other sports by extending `outcomes_json`
- `Simulator` takes a `TournamentFormat` + a match model — sport-agnostic
- Only `model/topscorer.py` is sport-specific; isolated behind a clear interface

## 11. Repo layout

```
worldcup/
├── pyproject.toml
├── README.md
├── docs/specs/2026-05-21-worldcup-design.md   ← this file
├── src/worldcup/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── models.py                  # Pydantic + SQLModel
│   ├── ingest/
│   │   ├── fixtures.py
│   │   ├── results.py
│   │   ├── lineups.py
│   │   ├── polymarket.py
│   │   ├── news.py
│   │   ├── reddit.py
│   │   └── twitter.py
│   ├── enrich/
│   │   ├── sentiment.py
│   │   └── aggregate.py
│   ├── model/
│   │   ├── elo.py
│   │   ├── match.py
│   │   ├── simulator.py
│   │   └── topscorer.py
│   ├── render/
│   │   ├── markdown.py
│   │   ├── dashboard.py
│   │   └── whatsapp_pickup.py
│   ├── api/
│   │   ├── app.py                 # FastAPI + fastapi-mcp
│   │   └── routes.py
│   ├── jobs/
│   │   └── daily.py               # APScheduler entrypoint
│   └── rationale/
│       └── prompts.py
└── tests/
    ├── test_simulator.py
    ├── test_match_model.py
    ├── test_tiebreakers.py
    └── test_topscorer.py
```

## 12. Open questions deferred to implementation

- Exact `goals_per_90` source for players who played sparingly in qualifying — likely fall back to per-team scoring rate × playing-time share
- Sports-data API choice on free-tier limits — football-data.org gives 10 req/min; sufficient for v0 but pre-validate
- Extra-time / penalty model for v1 (v0 uses a coin flip on draws in knockout)
- Rationale generation cost ceiling per refresh — set a per-run Claude token budget and fall back to template rationale if exceeded

## 13. Acceptance for v0

- Daily Markdown digest renders for every day from system deployment (target T−2mo) through the final
- Pre-tournament digests omit "Today's matches" and lead with tournament outlook + Golden Boot race; "Next matches" preview lists the 3 nearest fixtures
- The first daily digest is producible the day the system is deployed, with no completed-match data required
- Simulator produces tournament-level probabilities that sum to 100% (hard invariant)
- Smoke check: day-1 top-5 team `p_champion` are within ±10pp of Polymarket; large divergence is a flag to investigate priors, not a hard failure
- Top-scorer watchlist refresh triggers correctly after a hat-trick from an off-watchlist player
- WhatsApp bot successfully picks up and posts the daily file
- Dashboard responds in < 500ms for the "today" view
- All forecasts persist as snapshots; a re-run on the same input produces a byte-identical snapshot (modulo timestamp)
