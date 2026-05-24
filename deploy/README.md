# worldcup — Hetzner VPS deploy

End-to-end recipe for bringing worldcup up on a single Hetzner VPS. Assumes a
fresh Ubuntu 24.04 LTS image and shell access as a sudo-capable user. Adjust
paths and the service user as needed.

## 0. Prerequisites

- A Hetzner CX11 (or larger) VPS with Ubuntu 24.04 LTS
- DNS A record pointing to the VPS public IP (optional, for HTTPS via Caddy)
- API keys ready in your password manager:
  - football-data.org
  - Anthropic
  - GNews
  - Reddit (client id + secret)

## 1. System packages

```bash
sudo apt update && sudo apt install -y \
  python3.12 python3.12-venv \
  sqlite3 git curl ca-certificates
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec "$SHELL"  # reload PATH to pick up ~/.local/bin
```

## 2. Service user + directories

```bash
sudo useradd --system --create-home --home-dir /opt/worldcup --shell /usr/sbin/nologin worldcup
sudo mkdir -p /opt/worldcup/data /opt/worldcup/output
sudo chown -R worldcup:worldcup /opt/worldcup
```

## 3. Clone + install

Run as the `worldcup` user:

```bash
sudo -u worldcup bash <<'EOF'
cd /opt/worldcup
git clone <your-worldcup-git-url> code
ln -sf code/src
ln -sf code/migrations
ln -sf code/scripts
ln -sf code/pyproject.toml
ln -sf code/alembic.ini
ln -sf code/data
cd code
uv sync --all-extras
EOF
```

(The symlinks let the service WorkingDirectory at /opt/worldcup pick up the
shipped repo without rewriting paths — the venv lives under /opt/worldcup/code/.venv.)

worldcup depends on the `connectors` library via a git URL. `uv sync` pulls it automatically
from GitHub — no separate checkout needed.

Adjust the `ExecStart` path in the systemd unit if `.venv` lives elsewhere.

## 4. Environment file

```bash
sudo cp /opt/worldcup/code/deploy/env.production.example /opt/worldcup/.env
sudo chown worldcup:worldcup /opt/worldcup/.env
sudo chmod 600 /opt/worldcup/.env
sudo -u worldcup nano /opt/worldcup/.env   # fill in API keys
```

## 5. Database setup

```bash
sudo -u worldcup bash <<'EOF'
cd /opt/worldcup/code
uv run alembic upgrade head
uv run python scripts/seed_competition.py
EOF
```

## 6. systemd unit

```bash
sudo cp /opt/worldcup/code/deploy/worldcup.service /etc/systemd/system/worldcup.service
# Adjust ExecStart path if your .venv is at /opt/worldcup/code/.venv:
sudo sed -i 's|/opt/worldcup/.venv|/opt/worldcup/code/.venv|' /etc/systemd/system/worldcup.service
sudo systemctl daemon-reload
sudo systemctl enable --now worldcup.service
sudo systemctl status worldcup.service
```

Check logs:

```bash
journalctl -u worldcup.service -f
```

## 7. Smoke test

```bash
curl http://127.0.0.1:8765/healthz
# {"status":"ok"}

curl -X POST http://127.0.0.1:8765/refresh
# triggers a full pipeline run; see /opt/worldcup/output/YYYY-MM-DD.md for the digest

curl http://127.0.0.1:8765/api/tournament_outlook
# JSON forecast outlook
```

## 8. (Optional) Caddy reverse proxy + HTTPS

```bash
sudo apt install -y caddy
sudo bash -c 'cat > /etc/caddy/Caddyfile <<EOF
worldcup.example.com {
    reverse_proxy 127.0.0.1:8765
    basicauth /tournament /golden-boot /match/* /refresh {
        you JDJhJDEwJDcyMi5ETTRMQURDeXk0eUk2N3pjL3VHV3lEcGE5d3pHaVNGTzlGcEpQNzlFTGNUR3VTb2tH
    }
}
EOF'
sudo systemctl reload caddy
```

(Replace `worldcup.example.com` and the basic-auth user/hash. Generate the
hash with `caddy hash-password`.)

## 9. Updates

To pull a new version:

```bash
sudo -u worldcup bash <<'EOF'
cd /opt/worldcup/code
git pull
uv sync --all-extras
uv run alembic upgrade head
EOF
sudo systemctl restart worldcup.service
```

## Troubleshooting

- **Service won't start, exit code 1**: check `journalctl -u worldcup.service -n 100`. Most common: missing API key, wrong DATABASE_URL path permissions, or migrations not applied.
- **Daily refresh never fires**: confirm `DAILY_REFRESH_CRON` is in UTC. APScheduler runs in UTC.
- **Empty rationale section in digest**: `ANTHROPIC_API_KEY` not set (graceful degradation — pipeline still runs).
- **404 from /api/team_overview**: team not in DB. Run `/refresh` to ingest fixtures first.

## (Optional) WhatsApp daily delivery

worldcup ships an isolated WhatsApp bot under `wa-bot/` that posts the
daily digest to a WhatsApp group. **It does not interfere with any other
WhatsApp bot you may have running** — it uses its own session namespace
(`clientId="worldcup"`).

### One-time setup on the VPS

```bash
sudo apt install -y nodejs npm
# Chrome dependencies for whatsapp-web.js / puppeteer
sudo apt install -y libxss1 libgtk-3-0 libnss3 libasound2t64 libgbm1

sudo -u worldcup bash <<'EOF'
cd /opt/worldcup/code/wa-bot
npm install
cp .env.example /opt/worldcup/wa-bot.env
# Fill in WORLDCUP_GROUP_NAME and (optionally) override LATEST_DIGEST_PATH/FOOTER
EOF

# First run — scan the QR code from your phone. Run from a tty so QR
# renders properly:
sudo -u worldcup bash -c 'cd /opt/worldcup/code/wa-bot && set -a && source /opt/worldcup/wa-bot.env && set +a && npm start'
```

### systemd timer (daily at 09:05 UTC)

```bash
sudo cp /opt/worldcup/code/deploy/worldcup-wa.service /etc/systemd/system/
sudo cp /opt/worldcup/code/deploy/worldcup-wa.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now worldcup-wa.timer
sudo systemctl list-timers | grep worldcup-wa
```

Logs: `journalctl -u worldcup-wa.service -e`
