# worldcup — Plan 4: News/Reddit ingest + sentiment + Claude rationales

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Replace the empty rationale slot in match forecasts with Claude-written 2–3 sentence explanations. Pre-requisite: ingest match-relevant news + Reddit posts, score them for sentiment, aggregate per team/match. The product surface — *forecasts with reasoning, not just numbers* — finally lands.

**Architecture:**
- `ingest/news.py` (GNews) and `ingest/reddit.py` (Reddit via the existing `connectors` library) populate `NewsItem` + `SocialPost` tables, scoped per team and per match
- `enrich/sentiment.py` calls Claude in batches (cheap model) to score each new post → `SentimentScore` rows
- `enrich/aggregate.py` rolls scores up to team-level + match-level summaries
- `rationale/match.py` takes a fixture-known match + its context (form, odds, edge, sentiment, top news) → calls Claude (smart model) for a 2-3 sentence paragraph → persists on `MatchForecast.rationale_md`
- Budget guard: per-refresh token cap; if exceeded, fall back to a template "no rationale this run" line

**Tech stack additions:**
- `anthropic>=0.40.0` — Claude SDK
- `connectors[gnews,reddit]` — already declared (just enable the extras)

**Plan sequence:**
- Plans 1–3 ✅
- Plan 4 (this) — news/Reddit/sentiment/rationales
- Plan 5 — top-scorer model (Golden Boot)
- Plan 6 — HTMX dashboard + MCP exposure + Hetzner deploy

---

## What changes for the user

Before Plan 4, each per-match card in the digest shows:
```
### Brazil vs Switzerland · 21:00 UTC · Group G
- Our forecast: Brazil 62% · Draw 24% · Switzerland 14%
- Polymarket: Brazil 68% · Draw 22% · Switzerland 10%
- Edge: −6pp on Brazil
```

After Plan 4:
```
### Brazil vs Switzerland · 21:00 UTC · Group G
- Our forecast: Brazil 62% · Draw 24% · Switzerland 14%
- Polymarket: Brazil 68% · Draw 22% · Switzerland 10%
- Edge: −6pp on Brazil

Brazil's last two friendlies were unconvincing and Vinicius is doubtful;
market hasn't fully priced this in. Reddit sentiment around the squad has
softened over 48h. Still a clear favorite, but the price is short.

→ recent: [BBC: Vinicius doubtful] [Globo: Tite presser]
```

---

## Domain model additions

Three new tables + one column on the existing MatchForecast. One migration `0007_news_sentiment_rationale.py`.

```python
NewsItem
  id, competition_id, match_id|null, team_id|null,
  source ('gnews'), url (unique), ts, title, summary, raw_json

SocialPost
  id, competition_id, match_id|null, team_id|null,
  platform ('reddit'), external_id, ts, author, text, engagement,
  url (unique)

SentimentScore
  id, target_type ('post' | 'news_item' | 'team' | 'match'),
  target_id, ts, score (-1.0..1.0), confidence (0..1),
  model_version  -- e.g. "claude-haiku-4-5"

# Add column:
MatchForecast.rationale_md: Optional[str] = None
```

Both `NewsItem.url` and `SocialPost.url` are unique to make ingest idempotent.

---

## File structure

```
src/worldcup/
├── models/
│   ├── content.py             # NEW — NewsItem, SocialPost, SentimentScore
│   └── forecast.py            # add MatchForecast.rationale_md
├── ingest/
│   ├── news.py                # NEW
│   └── reddit.py              # NEW
├── enrich/
│   ├── __init__.py            # NEW
│   ├── claude_client.py       # NEW — thin AsyncAnthropic wrapper + budget guard
│   ├── sentiment.py           # NEW — score new posts via Claude
│   └── aggregate.py           # NEW — roll up post scores to team/match
├── rationale/
│   ├── __init__.py            # NEW
│   ├── prompts.py             # NEW — prompt templates
│   └── match.py               # NEW — generate per-match rationale
├── render/
│   └── templates/
│       └── digest_pretournament.md.j2  # surface rationale + recent links
└── jobs/
    └── refresh.py             # extend pipeline: news → reddit → sentiment → rationales

migrations/versions/
└── 0007_news_sentiment_rationale.py
```

## Configuration

New env vars (added to `.env.example` + `config.py`):
- `ANTHROPIC_API_KEY` — Claude SDK key
- `GNEWS_API_KEY` — GNews API key
- `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` + `REDDIT_USER_AGENT`
- `RATIONALE_TOKEN_BUDGET=100000` — per-refresh ceiling on Claude tokens
- `SENTIMENT_MODEL=claude-haiku-4-5` — cheap model for batch sentiment
- `RATIONALE_MODEL=claude-sonnet-4-5` — smart model for writeups

When any required key is missing the corresponding ingest/enrich step is **skipped with a warning log** (not an error). This lets the system run partially even before all keys are configured.

## Tasks

### Task 0: Schema additions (migration 0007)

- Define `NewsItem`, `SocialPost`, `SentimentScore` in new `models/content.py`
- Add `MatchForecast.rationale_md: Optional[str] = None`
- Generate migration `0007_news_sentiment_rationale.py`
- Migrate clean DB; verify new tables + column exist
- Full suite 73/73 still passing

### Task 1: Config + dependencies

- Add `anthropic>=0.40.0` to pyproject deps
- Re-declare `connectors` extras: `connectors[polymarket,gnews,reddit]`
- Add new settings: `anthropic_api_key`, `gnews_api_key`, `reddit_client_id/secret/user_agent`, `rationale_token_budget`, `sentiment_model`, `rationale_model`
- Update `.env.example`
- Quick smoke: `uv sync --all-extras && uv run python -c "import anthropic; print('ok')"`
- Commit

### Task 2: Claude client wrapper + budget guard

- `enrich/claude_client.py`:
  - `class ClaudeClient` wraps `AsyncAnthropic`; constructor takes api_key (None → disabled)
  - `async def score_text(text: str, model: str) -> dict` — sentiment scoring call
  - `async def complete(prompt: str, model: str, max_tokens: int) -> str` — generic completion
  - **Budget tracking**: per-instance counter of cumulative output tokens; raises `TokenBudgetExceeded` if a call would push over the cap
- Tests use a `FakeClaudeClient` (same interface, returns canned responses, counts calls)

### Task 3: News ingest (GNews via connectors)

- `ingest/news.py: ingest_news_for_teams(client, teams, lookback_hours=72)`
- For each team, query GNews with the team name; persist new `NewsItem` rows (unique by URL)
- Returns `{"items_inserted": int}`
- Test with a mocked GNews collector

### Task 4: Reddit ingest

- `ingest/reddit.py: ingest_reddit_for_competition(client, ...)`
- Pull recent posts from `r/soccer` + a small list of WC-relevant subs (`r/worldcup`, `r/footballtactics`). Optional team-specific subs deferred.
- Tag each post to a team if the team's name appears in the title/body
- Persist as `SocialPost` rows (unique by URL)
- Returns `{"posts_inserted": int}`

### Task 5: Sentiment scoring

- `enrich/sentiment.py: score_unscored_posts(claude_client, limit=50)`
- Pulls up to `limit` unscored posts (no `SentimentScore` row yet), batches them through Claude (cheap model), writes `SentimentScore` rows with `target_type="post" | "news_item"`
- Returns `{"posts_scored": int, "items_scored": int, "tokens_used": int}`
- Test asserts each new post gets a score row, calls Claude exactly once per batch (via FakeClaudeClient counters)

### Task 6: Aggregation

- `enrich/aggregate.py: aggregate_team_sentiment(as_of, lookback_hours=72)`
- For each team, take all `SentimentScore` rows with target_type ∈ {"post", "news_item"} where the underlying item is tagged to the team and `ts >= as_of - lookback`
- Compute weighted mean (by `confidence`) → upsert one `SentimentScore` row with `target_type="team"`
- Same shape for `aggregate_match_sentiment` (matches use both home and away teams' rollups + any match-tagged items)

### Task 7: Per-match rationale generation

- `rationale/match.py: generate_rationale_for_match(claude_client, match_id, snapshot_id)`
- Builds a structured prompt: team form (last 3 results), Elo ratings + delta, our 3-way prob, Polymarket prob, edge, top 3 news headlines per team (last 72h), per-team sentiment score with confidence, key injury flags (if surfaced in news headlines — best-effort string match for v0)
- Calls Claude (smart model), max 200 tokens; returns the markdown paragraph
- Updates the row on `MatchForecast.rationale_md`
- Test asserts the prompt contains all expected sections + the function writes to the correct row

### Task 8: Wire into refresh + render

- `jobs/refresh.py`: new steps between Elo updates and forecast generation:
  - news + reddit ingest (skip with warning if keys missing)
  - sentiment scoring of new posts/items
  - team/match sentiment aggregation
- After `generate_match_forecasts` writes MatchForecast rows: loop the rows, call `generate_rationale_for_match` for each. Respect the token budget — if exceeded, log + stop.
- Template update: render `m.rationale_md` (if present) below the per-match probs

### Task 9: Smoke + README

- Full-WC integration test with fake Claude returning canned rationale → assert one `MatchForecast` row has non-null `rationale_md`
- README: add Plan 4 section explaining the data flow + env vars

## Acceptance for Plan 4

- All previous tests still pass (73/73)
- A `run_refresh` with FakeClaudeClient produces:
  - `NewsItem` + `SocialPost` rows when respective ingests are mocked
  - `SentimentScore` rows for posts + per-team rollups
  - `MatchForecast.rationale_md` populated for at least one fixture-known match
- When `ANTHROPIC_API_KEY` is empty in config, `run_refresh` succeeds with a warning log and no rationale rows (graceful degradation)
- Token budget enforced: a `RATIONALE_TOKEN_BUDGET=0` run produces no rationale calls and no errors

## Explicit non-goals (v0)

- Sentence-level sentiment detail (we score whole posts)
- Multi-language news (English only)
- Twitter ingest (deferred — auth is fragile)
- Player-name extraction from news (Plan 5 territory)
- Image / video content
- Real-time streaming (we poll every refresh cycle)
- Tournament-level rationale ("notable movers" paragraph in tournament outlook) — deferred to a follow-up
