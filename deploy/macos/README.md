# worldcup on macOS — daily refresh + push to Cloudflare Pages

Sets up a launchd job that runs the worldcup pipeline daily, exports the
dashboard as static files, and pushes them to a Cloudflare Pages-connected
repo (which then auto-deploys to worldcup.zivalx.com).

## Prerequisites

- worldcup repo cloned at `~/repos_/worldcup` (or adjust paths in `refresh.sh`)
- `uv` installed (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `.env` file in `~/repos_/worldcup/.env` with all required API keys (see project root `.env.example`)
- A separate git repo connected to Cloudflare Pages — see "Cloudflare Pages setup" below

## Cloudflare Pages setup (one-time)

1. Create a new public-or-private GitHub repo, e.g. `worldcup-static`. It will hold the rendered HTML.
2. In Cloudflare dashboard → Pages → Create project → Connect to Git → select that repo, branch `worldcup-static` (we'll create that branch on first push).
3. Build settings: **none** (no build command, output directory `/`). It's pre-rendered HTML.
4. After it deploys once, attach custom domain `worldcup.zivalx.com` in Pages settings.

## Initial run (manual)

Before installing the launchd job, do a one-time verification:

```bash
cd ~/repos_/worldcup

# Set env vars for the push (the launchd plist doesn't run with your shell env)
export STATIC_REPO=git@github.com:YOUR_GH_USERNAME/worldcup-static.git
export WORLDCUP_BASE_URL=https://worldcup.zivalx.com

# Make sure SSH to GitHub works:
ssh -T git@github.com

# Run the script once:
./deploy/macos/refresh.sh

# Check the output:
tail -50 ~/Library/Logs/worldcup-refresh.log
```

If the push succeeded, visit your Cloudflare Pages deployment URL. The dashboard
should be there. Custom domain (worldcup.zivalx.com) propagates shortly.

## Install the launchd job

```bash
# Copy + customise the plist
cp deploy/macos/com.worldcup.daily.plist ~/Library/LaunchAgents/
# Edit the plist to bake STATIC_REPO + WORLDCUP_BASE_URL via EnvironmentVariables,
# OR add a wrapper script that sets them. Easiest:
$EDITOR ~/Library/LaunchAgents/com.worldcup.daily.plist
```

Add an `EnvironmentVariables` dict to the plist:

```xml
<key>EnvironmentVariables</key>
<dict>
  <key>STATIC_REPO</key>
  <string>git@github.com:YOUR_GH_USERNAME/worldcup-static.git</string>
  <key>WORLDCUP_BASE_URL</key>
  <string>https://worldcup.zivalx.com</string>
</dict>
```

Then load it:

```bash
launchctl unload ~/Library/LaunchAgents/com.worldcup.daily.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.worldcup.daily.plist
launchctl start com.worldcup.daily   # immediate test fire
```

Verify it's scheduled:

```bash
launchctl list | grep worldcup
```

## Caveats

- **Mac asleep at 09:00 UTC**: the job won't run while asleep. macOS Sequoia+
  honors `StartCalendarIntervalRunAtLoadMissed` and catches up on next wake;
  on older versions you may miss days. Keep the Mac plugged in, lid closed
  with external display, or run `caffeinate -d` in a background shell.
- **Network down at 09:00 UTC**: refresh.sh exits non-zero. Check the log,
  re-run manually.
- **SSH key for git push**: launchd doesn't load your normal shell env. Either
  use HTTPS with a personal access token in the URL, or ensure your SSH key
  has no passphrase (`ssh-keygen -p`), or use an SSH agent service that
  launchd can see.

## Logs

- `~/Library/Logs/worldcup-refresh.log` — script output, persistent
- `/tmp/worldcup-refresh.{stdout,stderr}.log` — launchd's view; ephemeral, cleared on reboot

## Disable / uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.worldcup.daily.plist
rm ~/Library/LaunchAgents/com.worldcup.daily.plist
```
