# worldcup daily refresh + static export + push to Cloudflare Pages.
# Triggered by the Windows Task Scheduler task "worldcup-daily".
# Configure via the environment variables baked into the task (or this script's
# defaults at the top).

# --- Config (edit if your paths differ) ---
$WORLDCUP_DIR  = if ($env:WORLDCUP_DIR)  { $env:WORLDCUP_DIR }  else { Join-Path $env:USERPROFILE 'repos\worldcup' }
$STATIC_BRANCH = if ($env:STATIC_BRANCH) { $env:STATIC_BRANCH } else { 'main' }
$STATIC_REPO   = $env:STATIC_REPO   # e.g. https://github.com/zivalx/worldcup-static.git — leave empty to skip push
$BASE_URL      = if ($env:WORLDCUP_BASE_URL) { $env:WORLDCUP_BASE_URL } else { 'https://worldcup.zivalx.com' }
$LOG_FILE      = Join-Path $env:USERPROFILE 'worldcup-refresh.log'

$ErrorActionPreference = 'Stop'

function Log {
    param([string]$msg)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    "[$stamp] $msg" | Tee-Object -FilePath $LOG_FILE -Append
}

try {
    Log "worldcup daily refresh starting"
    Log "  WORLDCUP_DIR=$WORLDCUP_DIR"
    Log "  STATIC_REPO=$STATIC_REPO"
    Log "  BASE_URL=$BASE_URL"

    Set-Location $WORLDCUP_DIR

    # 1. Pipeline refresh
    Log "Step 1/3: running uv run worldcup refresh"
    & uv run worldcup refresh --trigger=daily 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -ne 0) { throw "worldcup refresh failed (exit $LASTEXITCODE)" }

    # 2. Static export
    $exportDir = Join-Path $env:TEMP "worldcup-static-$(Get-Random)"
    New-Item -ItemType Directory -Path $exportDir | Out-Null
    Log "Step 2/3: exporting static site to $exportDir"
    & uv run worldcup export-static --output-dir $exportDir --base-url $BASE_URL 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -ne 0) { throw "worldcup export-static failed (exit $LASTEXITCODE)" }

    # 3. Push to Cloudflare Pages (optional)
    if ($STATIC_REPO) {
        $pushDir = Join-Path $env:TEMP "worldcup-push-$(Get-Random)"
        Log "Step 3/3: cloning $STATIC_REPO into $pushDir"
        & git clone --depth 1 -b $STATIC_BRANCH $STATIC_REPO $pushDir 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
        if ($LASTEXITCODE -ne 0) {
            Log "Branch $STATIC_BRANCH didn't exist; cloning default and creating it"
            & git clone --depth 1 $STATIC_REPO $pushDir 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
            if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
            Set-Location $pushDir
            & git checkout -b $STATIC_BRANCH 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
        } else {
            Set-Location $pushDir
        }

        # Wipe existing content + copy new export
        Get-ChildItem -Force | Where-Object { $_.Name -ne '.git' } | Remove-Item -Recurse -Force
        Copy-Item -Path (Join-Path $exportDir '*') -Destination $pushDir -Recurse

        & git add -A 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
        $status = & git status --porcelain
        if ([string]::IsNullOrWhiteSpace($status)) {
            Log "No changes to push."
        } else {
            $msg = "refresh: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
            & git -c user.email=worldcup-bot@local -c user.name=worldcup-bot commit -m $msg 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
            & git push origin $STATIC_BRANCH 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
            if ($LASTEXITCODE -ne 0) { throw "git push failed" }
            Log "Pushed to $STATIC_BRANCH."
        }

        # Cleanup temp dirs
        Set-Location $WORLDCUP_DIR
        Remove-Item -Path $pushDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Log "Step 3/3: STATIC_REPO not set; skipping push"
    }

    Remove-Item -Path $exportDir -Recurse -Force -ErrorAction SilentlyContinue
    Log "worldcup daily refresh done"
    exit 0
}
catch {
    Log "ERROR: $_"
    Log $_.ScriptStackTrace
    exit 1
}
