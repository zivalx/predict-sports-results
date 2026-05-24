# worldcap — Hetzner VPS deploy

End-to-end recipe for bringing worldcap up on a single Hetzner VPS. Assumes a
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
sudo useradd --system --create-home --home-dir /opt/worldcap --shell /usr/sbin/nologin worldcap
sudo mkdir -p /opt/worldcap/data /opt/worldcap/output
sudo chown -R worldcap:worldcap /opt/worldcap
```

## 3. Clone + install

Run as the `worldcap` user:

```bash
sudo -u worldcap bash <<'EOF'
cd /opt/worldcap
git clone <your-worldcap-git-url> code
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

(The symlinks let the service WorkingDirectory at /opt/worldcap pick up the
shipped repo without rewriting paths — the venv lives under /opt/worldcap/code/.venv.)

Adjust the `ExecStart` path in the systemd unit if `.venv` lives elsewhere.

## 4. Environment file

```bash
sudo cp /opt/worldcap/code/deploy/env.production.example /opt/worldcap/.env
sudo chown worldcap:worldcap /opt/worldcap/.env
sudo chmod 600 /opt/worldcap/.env
sudo -u worldcap nano /opt/worldcap/.env   # fill in API keys
```

## 5. Database setup

```bash
sudo -u worldcap bash <<'EOF'
cd /opt/worldcap/code
uv run alembic upgrade head
uv run python scripts/seed_competition.py
EOF
```

## 6. systemd unit

```bash
sudo cp /opt/worldcap/code/deploy/worldcap.service /etc/systemd/system/worldcap.service
# Adjust ExecStart path if your .venv is at /opt/worldcap/code/.venv:
sudo sed -i 's|/opt/worldcap/.venv|/opt/worldcap/code/.venv|' /etc/systemd/system/worldcap.service
sudo systemctl daemon-reload
sudo systemctl enable --now worldcap.service
sudo systemctl status worldcap.service
```

Check logs:

```bash
journalctl -u worldcap.service -f
```

## 7. Smoke test

```bash
curl http://127.0.0.1:8765/healthz
# {"status":"ok"}

curl -X POST http://127.0.0.1:8765/refresh
# triggers a full pipeline run; see /opt/worldcap/output/YYYY-MM-DD.md for the digest

curl http://127.0.0.1:8765/api/tournament_outlook
# JSON forecast outlook
```

## 8. (Optional) Caddy reverse proxy + HTTPS

```bash
sudo apt install -y caddy
sudo bash -c 'cat > /etc/caddy/Caddyfile <<EOF
worldcap.example.com {
    reverse_proxy 127.0.0.1:8765
    basicauth /tournament /golden-boot /match/* /refresh {
        you JDJhJDEwJDcyMi5ETTRMQURDeXk0eUk2N3pjL3VHV3lEcGE5d3pHaVNGTzlGcEpQNzlFTGNUR3VTb2tH
    }
}
EOF'
sudo systemctl reload caddy
```

(Replace `worldcap.example.com` and the basic-auth user/hash. Generate the
hash with `caddy hash-password`.)

## 9. Updates

To pull a new version:

```bash
sudo -u worldcap bash <<'EOF'
cd /opt/worldcap/code
git pull
uv sync --all-extras
uv run alembic upgrade head
EOF
sudo systemctl restart worldcap.service
```

## Troubleshooting

- **Service won't start, exit code 1**: check `journalctl -u worldcap.service -n 100`. Most common: missing API key, wrong DATABASE_URL path permissions, or migrations not applied.
- **Daily refresh never fires**: confirm `DAILY_REFRESH_CRON` is in UTC. APScheduler runs in UTC.
- **Empty rationale section in digest**: `ANTHROPIC_API_KEY` not set (graceful degradation — pipeline still runs).
- **404 from /api/team_overview**: team not in DB. Run `/refresh` to ingest fixtures first.
