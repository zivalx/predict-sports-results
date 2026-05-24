# worldcup WA bot

Posts the worldcup daily digest to a configured WhatsApp group. Fire-once
process — invoke from cron daily.

**Completely isolated from the existing `whatsapp-daily-bot/` at
`../../whatsapp-daily-bot/`**:

- Lives in its own directory
- Stores WhatsApp session under its own `clientId="worldcup"` namespace
- Targets a different group (configurable)
- Doesn't share any config, state, or process with the existing bot

You can run both bots on the same WhatsApp account by linking the worldcup
bot as a second device (WhatsApp allows up to 4 linked devices per account).

## Setup

```bash
cd worldcup/wa-bot
npm install
cp .env.example .env
# Edit .env — set WORLDCUP_GROUP_NAME to the exact group name from
# WhatsApp Web (web.whatsapp.com)
```

## First run (QR scan)

```bash
npm start
```

On first invocation a QR code appears in the terminal. On your phone:
**WhatsApp → Settings → Linked Devices → Link a Device → scan the QR.**

The session is then cached under `.wwebjs_auth/session-worldcup/` and
subsequent runs reuse it without prompting.

## Daily cron

Once setup is working, add to your crontab — e.g. for 09:00 daily:

```cron
0 9 * * * cd /opt/worldcup/wa-bot && /usr/bin/npm start >> /var/log/worldcup-wa.log 2>&1
```

(Adjust paths for your environment.)

## How it works

1. Reads `LATEST_DIGEST_PATH` (default: `../output/latest.md`).
2. Connects to WhatsApp with `clientId="worldcup"`.
3. Finds the group named `WORLDCUP_GROUP_NAME`.
4. Posts the digest content + optional `FOOTER`.
5. Waits for server ACK, then exits.

If the digest file is missing/empty or the group can't be found, the bot
exits with a non-zero code and logs the available groups.

## Troubleshooting

- **Group not found**: name must match exactly as in WhatsApp Web (special
  characters and RTL languages can look different in terminal).
- **Conflict with existing bot**: shouldn't happen — different `clientId`
  means different session dir. If you ever want a clean slate, delete
  `.wwebjs_auth/session-worldcup/` and re-scan QR.
- **Headless on a VPS**: `puppeteer` requires Chrome dependencies. On
  Ubuntu: `sudo apt install -y libxss1 libgtk-3-0 libnss3 libasound2t64 libgbm1`.
