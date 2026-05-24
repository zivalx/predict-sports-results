# worldcup on Windows — daily refresh + push to Cloudflare Pages

End-to-end recipe for running worldcup on a personal Windows PC, with the
public dashboard served from `worldcup.zivalx.com` via Cloudflare Pages.

Architecture: the Python pipeline runs locally on your PC via Windows Task
Scheduler. After each refresh, the static dashboard is pushed to a Cloudflare
Pages-connected GitHub repo, which auto-deploys.

## Prerequisites

Install on your Windows PC:

- **Python 3.12+**: https://www.python.org/downloads/ (during install, tick "Add to PATH")
- **uv**: in PowerShell — `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **Git for Windows**: https://git-scm.com/download/win — installs `git` + Git Bash + Git Credential Manager
- **PowerShell 7+** (optional but recommended): `winget install --id Microsoft.Powershell`

Verify:
```powershell
python --version    # 3.12+
uv --version        # any recent
git --version       # any recent
```

## 1. Clone the repos

In PowerShell:

```powershell
cd $HOME
mkdir repos
cd repos
git clone <your-worldcup-repo-url> worldcup
git clone <github.com/zivalx/collectors-or-whatever-the-url-is> collectors  # only needed if you want to edit connectors locally
```

(The `collectors` clone is optional — worldcup pulls it from github.com/zivalx/collectors via `uv sync`. Cloning locally enables the `[tool.uv.sources]` override for editable development. Skip if you don't plan to modify the connectors library.)

## 2. Install dependencies

```powershell
cd $HOME\repos\worldcup
uv sync --all-extras
```

This installs Python deps + the `worldcup` CLI entry point.

## 3. Configure `.env`

```powershell
copy .env.example .env
notepad .env     # or your preferred editor
```

Fill in:
- `FOOTBALL_DATA_API_KEY` — required
- `ANTHROPIC_API_KEY` — required for sentiment + rationale writing (system gracefully degrades if blank)
- `GNEWS_API_KEY` — required for news ingest (blank → news skipped)
- `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` — optional (blank → Reddit skipped)

Save the file. **Important:** `.env` is gitignored — never commit it.

## 4. Initialize the database

```powershell
uv run alembic upgrade head
uv run python scripts/seed_competition.py
```

## 5. First manual refresh

```powershell
uv run worldcup refresh
```

This hits the real APIs and populates the DB. Watch for `forecast.per_match forecasts_written=72` (or similar) — that confirms predictions for all group-stage matches were generated.

## 6. Inspect the dashboard locally

```powershell
uv run worldcup serve --port 8765
```

Open http://localhost:8765 in a browser. You should see the dashboard with real forecasts for World Cup 2026.

Press Ctrl-C in PowerShell to stop the server.

## 7. Set up Cloudflare Pages (one-time)

1. Create a new empty private GitHub repo for the rendered HTML, e.g. `worldcup-static`:
   ```powershell
   gh repo create worldcup-static --private --description "Static dashboard for worldcup"
   ```
2. In Cloudflare dashboard → Pages → Create project → Connect to Git → select `worldcup-static`, branch `main`.
3. Build settings: leave the build command **empty**, output directory `/`. We push pre-rendered HTML; no build needed.
4. After the first (empty) deploy, attach custom domain `worldcup.zivalx.com` in Pages settings.

## 8. Test the static-export → CF Pages flow once

```powershell
$env:STATIC_REPO = "git@github.com:YOUR_GH_USERNAME/worldcup-static.git"
$env:WORLDCUP_BASE_URL = "https://worldcup.zivalx.com"

.\deploy\windows\refresh.ps1
```

This runs the whole flow: refresh → export → push. Watch the log:

```powershell
Get-Content -Tail 100 -Wait $env:USERPROFILE\worldcup-refresh.log
```

If push succeeds, visit `worldcup.zivalx.com` in ~30 seconds — should show the dashboard.

## 9. Schedule it daily

```powershell
cd $HOME\repos\worldcup
.\deploy\windows\Register-Task.ps1 `
    -WorldcupDir "$HOME\repos\worldcup" `
    -StaticRepo "git@github.com:YOUR_GH_USERNAME/worldcup-static.git" `
    -BaseUrl "https://worldcup.zivalx.com" `
    -DailyTimeUtc "09:00"
```

Because Task Scheduler doesn't support direct environment-variable injection at
the task level, configure `STATIC_REPO` and `WORLDCUP_BASE_URL` as persistent
user environment variables (Win+R → `sysdm.cpl` → Advanced → Environment
Variables → User variables), **or** edit the defaults at the top of
`refresh.ps1` directly.

Confirm:
```powershell
Get-ScheduledTaskInfo -TaskName 'worldcup-daily'
```

Trigger an immediate test:
```powershell
Start-ScheduledTask -TaskName 'worldcup-daily'
```

Watch the log file:
```powershell
Get-Content -Tail 100 -Wait $env:USERPROFILE\worldcup-refresh.log
```

You should see a full refresh log ending with "worldcup daily refresh done".

## 10. Verify it'll run unattended

- Leave your PC on, logged in (Task Scheduler runs as a logged-in user task)
- Sleep is OK — Task Scheduler wakes the PC briefly to run, then it sleeps again. **Lid closed on a laptop generally still works on Windows**, unlike macOS.
- If you turn off the PC overnight, the task fires on next boot (`-StartWhenAvailable` flag)

## Daily flow

Once set up, every day at 09:00 UTC (or whatever you chose):
1. Task Scheduler triggers `refresh.ps1`
2. Script runs full pipeline: ingest → forecast → render → export → push
3. Cloudflare Pages auto-deploys the pushed static HTML
4. `worldcup.zivalx.com` shows the new forecast within ~30 sec of the push completing

You only intervene if:
- An API key expires (rotate it, edit `.env`)
- A new connectors version is released (bump the SHA in `pyproject.toml`)
- Something breaks (check `~\worldcup-refresh.log`)

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "uv: command not found" | uv not in PATH | Restart PowerShell after installing uv |
| Task doesn't fire | Computer is off / not logged in | Check `Get-ScheduledTaskInfo` LastRunResult and NextRunTime |
| Git push fails with auth error | Git Credential Manager not set up for the GitHub repo | Run `gh auth login` once interactively |
| `forecasts_written=0` | football-data.org returning unexpected status values | Already handled by `_STATUS_MAP` in ingest/sports_data.py; if still 0, post the log |
| Polymarket SSL errors | Some networks intercept HTTPS with corporate certs | Run from a different network OR see deploy/cloudflare-tunnel.md for workarounds |
| `~\worldcup-refresh.log` not appearing | Permissions issue or Task Scheduler running as different user | Check Task Properties → "Run as" matches your username |

## (Optional) Cloudflare Tunnel for private MCP access

If you want your friends' Claude agents to query worldcup, follow
`deploy/cloudflare-tunnel.md` — `cloudflared` has a Windows installer.
Run it as a Windows service alongside the Task Scheduler refresh job.
