# worldcup — Plan 6: HTMX dashboard + MCP exposure + deploy

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Make worldcup consumable beyond the Markdown digest. Three deliverables:
1. A lightweight **HTMX dashboard** at `/` for browsing the latest snapshot (tournament outlook, Golden Boot, per-match cards, snapshot history).
2. **MCP server** mounted at `/mcp` exposing the forecast data as tools so agents (Claude, Navigator, etc.) can query worldcup directly.
3. **Production deploy artifacts** — systemd unit, env reference, a deploy README — targeting the Hetzner VPS path the user already plans for.

**Architecture:**
- HTMX + Jinja2 templates served by FastAPI. No JS framework. CSS scoped to a single `static/dashboard.css`. Pages are server-rendered HTML; HTMX partial swaps for the "refresh" button.
- `fastapi-mcp` auto-exposes annotated JSON endpoints as MCP tools (matches trender's pattern).
- Deploy artifacts go under `deploy/` — systemd service unit, env reference, and a step-by-step README for bringing the service up on a Hetzner VPS.

**Tech stack additions:** `fastapi-mcp>=0.3.0`. Jinja2 is already a dep.

**Plan sequence:** Plans 1–5 ✅. Plan 6 (this) is the final v0 plan.

---

## What changes for the user

A working web UI at `http://host:port/`:
- **Home**: today's snapshot summary — top 5 champion contenders, today's matches preview, "last refreshed" timestamp + manual refresh button
- **Tournament**: full sortable outlook table (Champion %, Runner-up %, Semi %, Top group %, Edge vs market)
- **Match detail** at `/match/<id>`: full per-match card with rationale + recent headlines list
- **Golden Boot**: full ranked watchlist table

And an MCP endpoint at `/mcp` exposing:
- `get_tournament_outlook(top_n)` → list of `{team, p_champion, p_runner_up, p_semi, p_top_group, poly_p_champion, edge}`
- `get_match_forecast(home_team, away_team)` → `{p_home, p_draw, p_away, edge_vs_poly, rationale_md, news_links}`
- `get_golden_boot_race(top_n)` → list of `{player, team, p_golden_boot, expected_goals, poly_p, edge}`
- `get_team_overview(team_name)` → `{rating, p_champion, sentiment, recent_news_titles, upcoming_matches}`

And a Hetzner deploy recipe under `deploy/`.

---

## File structure

```
src/worldcup/
├── api/
│   ├── app.py              # mount dashboard router + MCP
│   ├── dashboard.py        # NEW — HTML routes
│   ├── mcp_endpoints.py    # NEW — JSON endpoints designed for MCP exposure
│   └── templates/
│       ├── base.html       # NEW
│       ├── home.html       # NEW
│       ├── tournament.html # NEW
│       ├── golden_boot.html # NEW
│       ├── match_detail.html # NEW
│       └── _refresh_button.html  # HTMX partial
│   └── static/
│       └── dashboard.css   # NEW

deploy/
├── README.md               # NEW — step-by-step Hetzner deploy
├── worldcup.service        # NEW — systemd unit
└── env.production.example  # NEW — required env vars in production
```

## Tasks

### Task 0: Dependencies + scaffolding

- Add `fastapi-mcp>=0.3.0` to `pyproject.toml`
- Create `src/worldcup/api/templates/` and `src/worldcup/api/static/`
- Configure FastAPI to serve `static/` and load templates from `templates/`
- Add `base.html` (header, nav, footer scaffold) + `dashboard.css`
- One smoke test: `GET /static/dashboard.css` returns 200
- Full suite still 110 passing

### Task 1: Dashboard home page

- Add `dashboard.py` with `home_router = APIRouter()`
- `GET /` returns rendered `home.html` showing:
  - "Day X · Y days to kickoff" header
  - Top-5 champion contenders table
  - Today's matches (3 nearest fixture-known matches)
  - "Last refreshed at <ts>" + "Refresh now" button (HTMX `hx-post="/refresh"`)
- Mount the router in `build_app`
- Test the route renders 200 + contains expected text

### Task 2: Tournament outlook page

- `GET /tournament` renders `tournament.html`
- Sortable table (HTMX-driven re-sort on header click, swap via partial; or accept simpler static-sort v0)
- Tests: route returns 200, table includes all teams from latest snapshot

### Task 3: Per-match detail page

- `GET /match/<match_id>` renders `match_detail.html`
- Shows: matchup header, our 3-way prob, Polymarket, edge, rationale_md (rendered to HTML), recent news links per team
- Tests: route returns 200 with rationale text + headlines

### Task 4: Golden Boot page

- `GET /golden-boot` renders `golden_boot.html`
- Full ranked table (all watchlist players)
- Tests: route returns 200 + table includes player names

### Task 5: MCP-friendly JSON endpoints + fastapi-mcp mount

- `src/worldcup/api/mcp_endpoints.py` — typed JSON endpoints with Pydantic response models + clear docstrings (these become the MCP tool descriptions)
- 4 endpoints: `get_tournament_outlook`, `get_match_forecast`, `get_golden_boot_race`, `get_team_overview`
- Mount via `fastapi-mcp` in `build_app`
- Tests: each endpoint returns the expected JSON shape

### Task 6: Deploy artifacts + README

- `deploy/worldcup.service` — systemd unit (uvicorn + worldcup.api.app + env file)
- `deploy/env.production.example` — required env vars
- `deploy/README.md` — step-by-step Hetzner VPS setup: install uv, clone repo, install deps, alembic upgrade, seed competition, configure systemd, start service, optional Caddy reverse proxy snippet for HTTPS

### Task 7: Final smoke + main README update

- Full pytest suite passes
- README adds Plan 6 section linking deploy/README.md and listing the new routes + MCP endpoints

## Acceptance for Plan 6

- All previous tests still pass (110/110)
- New dashboard tests pass (smoke: each page returns 200 + key strings)
- MCP endpoint tests pass (correct JSON shapes)
- `deploy/worldcup.service` is a valid systemd unit (parseable)
- A fresh clone + `uv sync && uv run alembic upgrade head && uv run python scripts/seed_competition.py && uv run uvicorn worldcup.api.app:app` brings the service up and `/` returns the dashboard

## Explicit non-goals (v0)

- Auth / login (deploy README will recommend reverse-proxy-level basic auth)
- WebSocket live updates (HTMX poll on the home page is enough)
- Mobile-optimised CSS beyond what naturally responsive grids give us
- Multi-tenant support
- Docker image (systemd is sufficient for single-VPS deploy)
