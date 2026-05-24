#!/usr/bin/env bash
# worldcap daily refresh + static export + push to Cloudflare Pages.
# Triggered by ~/Library/LaunchAgents/com.worldcap.daily.plist
set -euo pipefail

# --- Config (edit to match your machine) ---
WORLDCAP_DIR="${WORLDCAP_DIR:-$HOME/repos_/worldcap}"
STATIC_BRANCH="${STATIC_BRANCH:-worldcup-static}"
STATIC_REPO="${STATIC_REPO:-}"  # e.g. git@github.com:ziva/worldcap-static.git — leave empty to skip git push
LOG_FILE="${HOME}/Library/Logs/worldcap-refresh.log"

# --- Setup ---
exec > >(tee -a "$LOG_FILE") 2>&1
echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] worldcap daily refresh starting"

cd "$WORLDCAP_DIR"

# --- 1. Pipeline refresh ---
uv run worldcap refresh --trigger=daily

# --- 2. Static export ---
EXPORT_DIR="$(mktemp -d -t worldcap-static-XXXXXX)"
trap 'rm -rf "$EXPORT_DIR"' EXIT
uv run worldcap export-static \
  --output-dir "$EXPORT_DIR" \
  --base-url "${WORLDCAP_BASE_URL:-https://worldcup.zivalx.com}"

echo "Exported static site to $EXPORT_DIR"
ls -la "$EXPORT_DIR" | head -20

# --- 3. Push to Cloudflare Pages (optional — only if STATIC_REPO is set) ---
if [ -n "$STATIC_REPO" ]; then
  PUSH_DIR="$(mktemp -d -t worldcap-push-XXXXXX)"
  trap 'rm -rf "$EXPORT_DIR" "$PUSH_DIR"' EXIT

  git clone --depth 1 -b "$STATIC_BRANCH" "$STATIC_REPO" "$PUSH_DIR" 2>/dev/null || {
    git clone --depth 1 "$STATIC_REPO" "$PUSH_DIR"
    cd "$PUSH_DIR"
    git checkout -b "$STATIC_BRANCH"
  }
  cd "$PUSH_DIR"
  rm -rf ./*
  cp -R "$EXPORT_DIR"/* .
  git add -A
  if git diff --cached --quiet; then
    echo "No changes to push."
  else
    git -c user.email=worldcap-bot@local -c user.name=worldcap-bot commit -m "refresh: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push origin "$STATIC_BRANCH"
    echo "Pushed to $STATIC_BRANCH."
  fi
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] worldcap daily refresh done"
