# worldcap daily refresh + static export + push to Cloudflare Pages.
# Triggered by the Windows Task Scheduler task "worldcap-daily".
# Configure via the environment variables baked into the task (or this script's
# defaults at the top).

# --- Config (edit if your paths differ) ---
$WORLDCAP_DIR  = if ($env:WORLDCAP_DIR)  { $env:WORLDCAP_DIR }  else { Join-Path $env:USERPROFILE 'repos\worldcap' }
$STATIC_BRANCH = if ($env:STATIC_BRANCH) { $env:STATIC_BRANCH } else { 'main' }
$STATIC_REPO   = $env:STATIC_REPO   # e.g. https://github.com/zivalx/worldcap-static.git — leave empty to skip push
$BASE_URL      = if ($env:WORLDCAP_BASE_URL) { $env:WORLDCAP_BASE_URL } else { 'https://worldcup.zivalx.com' }
$LOG_FILE      = Join-Path $env:USERPROFILE 'worldcap-refresh.log'

$ErrorActionPreference = 'Stop'

function Log {
    param([string]$msg)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    "[$stamp] $msg" | Tee-Object -FilePath $LOG_FILE -Append
}

try {
    Log "worldcap daily refresh starting"
    Log "  WORLDCAP_DIR=$WORLDCAP_DIR"
    Log "  STATIC_REPO=$STATIC_REPO"
    Log "  BASE_URL=$BASE_URL"

    Set-Location $WORLDCAP_DIR

    # 1. Pipeline refresh
    Log "Step 1/3: running uv run worldcap refresh"
    & uv run worldcap refresh --trigger=daily 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -ne 0) { throw "worldcap refresh failed (exit $LASTEXITCODE)" }

    # 2. Static export
    $exportDir = Join-Path $env:TEMP "worldcap-static-$(Get-Random)"
    New-Item -ItemType Directory -Path $exportDir | Out-Null
    Log "Step 2/3: exporting static site to $exportDir"
    & uv run worldcap export-static --output-dir $exportDir --base-url $BASE_URL 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -ne 0) { throw "worldcap export-static failed (exit $LASTEXITCODE)" }

    # 3. Push to Cloudflare Pages (optional)
    if ($STATIC_REPO) {
        $pushDir = Join-Path $env:TEMP "worldcap-push-$(Get-Random)"
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
            & git -c user.email=worldcap-bot@local -c user.name=worldcap-bot commit -m $msg 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
            & git push origin $STATIC_BRANCH 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
            if ($LASTEXITCODE -ne 0) { throw "git push failed" }
            Log "Pushed to $STATIC_BRANCH."
        }

        # Cleanup temp dirs
        Set-Location $WORLDCAP_DIR
        Remove-Item -Path $pushDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Log "Step 3/3: STATIC_REPO not set; skipping push"
    }

    Remove-Item -Path $exportDir -Recurse -Force -ErrorAction SilentlyContinue
    Log "worldcap daily refresh done"
    exit 0
}
catch {
    Log "ERROR: $_"
    Log $_.ScriptStackTrace
    exit 1
}
