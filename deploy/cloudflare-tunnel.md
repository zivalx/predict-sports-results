# worldcap MCP via Cloudflare Tunnel (private, shared with friends)

Expose your locally-running worldcap (on Mac or Windows, port 8765) as a
private subdomain like `api.zivalx.com` (or `mcp.zivalx.com`), gated by
Cloudflare Access so only emails on your allowlist can reach it.

This setup is the lightweight alternative to running a separate VPS. The
forecast pipeline still runs on your local machine and pushes the public
dashboard to Cloudflare Pages (see `deploy/macos/README.md` or
`deploy/windows/README.md`); this just exposes the live HTTP API for agent
queries.

## Windows-specific setup

Installing and running `cloudflared` on Windows differs slightly from macOS:

- **Download**: grab `cloudflared-windows-amd64.exe` from
  https://github.com/cloudflare/cloudflared/releases/latest and place it
  somewhere on your `PATH` (e.g. `C:\Program Files\cloudflared\cloudflared.exe`).
  Alternatively, install via winget:
  ```powershell
  winget install --id Cloudflare.cloudflared
  ```
- **Authenticate + create tunnel + DNS**: run the same commands as macOS
  (Steps 1–3 below), just replace `cloudflared` with `cloudflared.exe` if
  it's not on your `PATH`.
- **Install as a Windows service** (Step 7 equivalent):
  ```powershell
  # Run this once from an elevated (Admin) PowerShell:
  cloudflared.exe service install --token YOUR_TUNNEL_TOKEN
  ```
  This registers `cloudflared` as a Windows Service that starts automatically
  on boot — no launchd needed. Verify in `services.msc` that
  "Cloudflare Tunnel" is running.
- **Config file location**: on Windows, `cloudflared` reads from
  `%USERPROFILE%\.cloudflared\config.yml` (same YAML structure as macOS).
- **Tunnel credentials**: stored in `%USERPROFILE%\.cloudflared\<UUID>.json`
  (macOS stores them in `~/.cloudflared/`).

Everything else — authentication, tunnel creation, DNS routing, CF Access
policy — is identical on Windows and macOS. Continue with Step 1 below.

## Prerequisites

- Cloudflare account managing zivalx.com (you already have this for Pages)
- `cloudflared` installed:
  - **macOS**: `brew install cloudflared`
  - **Windows**: see Windows-specific setup above
- worldcap running locally on port 8765

## Step 1: Authenticate cloudflared

```bash
cloudflared tunnel login
```

This opens a browser, you pick zivalx.com, and a cert is saved to
`~/.cloudflared/cert.pem`.

## Step 2: Create the tunnel

```bash
cloudflared tunnel create worldcap
```

This writes a tunnel UUID + credentials JSON to `~/.cloudflared/<UUID>.json`.
Note the UUID — you'll reference it below.

## Step 3: Create the DNS record

Use whatever hostname you want; example: `api.zivalx.com`.

```bash
cloudflared tunnel route dns worldcap api.zivalx.com
```

## Step 4: Configure the tunnel

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /Users/YOU/.cloudflared/<YOUR_TUNNEL_UUID>.json

ingress:
  - hostname: api.zivalx.com
    service: http://localhost:8765
  - service: http_status:404
```

## Step 5: Test the tunnel

In one terminal, start worldcap:

```bash
cd ~/repos_/worldcap
uv run worldcap serve --port 8765
```

In another:

```bash
cloudflared tunnel run worldcap
```

Visit https://api.zivalx.com/healthz — should return `{"status":"ok"}`.

## Step 6: Gate it with Cloudflare Access (free tier)

In Cloudflare dashboard → Zero Trust → Access → Applications → Add an application.

- Type: Self-hosted
- Application name: worldcap MCP
- Application domain: api.zivalx.com
- Identity provider: One-time PIN (email) — works without setting up Google/etc
- Policy: "Allow", rule = "Emails" with the addresses of you + your friends

After saving, hitting api.zivalx.com requires the visitor to enter their email
and click a one-time PIN. Cloudflare sets a session cookie valid for the
configured duration (default 24h). MCP clients (Claude Desktop etc.) can pass
the `cf-access-client-id` / `cf-access-client-secret` headers from a "service
token" if you want them to authenticate non-interactively — see Cloudflare's
docs for `Service Tokens`.

## Step 7: Run cloudflared as a service

```bash
sudo cloudflared service install
sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```

Now the tunnel is up whenever your Mac is on, independent of any terminal.

## Friends' setup

To use worldcap from Claude Desktop:

1. Visit https://api.zivalx.com once in a browser, authenticate via PIN.
2. In Claude Desktop config, add:

```json
{
  "mcpServers": {
    "worldcap": {
      "url": "https://api.zivalx.com/mcp",
      "headers": {
        "Cookie": "<copy from browser devtools after authenticating>"
      }
    }
  }
}
```

(A cleaner approach uses Cloudflare Service Tokens — see CF docs.)

## Caveats

- **Mac asleep**: the tunnel dies when the Mac sleeps. Lid-closed-with-external-display
  works. Or run worldcap on a Raspberry Pi at home that's always on.
- **Public IP not required**: Cloudflare Tunnel uses outbound connections only,
  so you don't need port forwarding or a static IP.
- **One tunnel, multiple services**: you can route api.zivalx.com to worldcap
  and (later) other paths to other services from the same `config.yml`.
