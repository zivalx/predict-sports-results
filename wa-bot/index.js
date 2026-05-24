import 'dotenv/config';
import { readFileSync, existsSync } from 'fs';
import { resolve, dirname, isAbsolute } from 'path';
import { fileURLToPath } from 'url';
import qrcode from 'qrcode-terminal';
import pkg from 'whatsapp-web.js';

const { Client, LocalAuth } = pkg;

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── Config ───────────────────────────────────────────────────────────────────
const WORLDCUP_GROUP_NAME = process.env.WORLDCUP_GROUP_NAME;
const LATEST_DIGEST_PATH_RAW = process.env.LATEST_DIGEST_PATH || '../output/latest.md';
const FOOTER = (process.env.FOOTER ?? '').replace(/\\n/g, '\n');

const LATEST_DIGEST_PATH = isAbsolute(LATEST_DIGEST_PATH_RAW)
  ? LATEST_DIGEST_PATH_RAW
  : resolve(__dirname, LATEST_DIGEST_PATH_RAW);

function log(msg) {
  console.log(`[${new Date().toISOString()}] ${msg}`);
}
function logError(msg) {
  console.error(`[${new Date().toISOString()}] ERROR: ${msg}`);
}

if (!WORLDCUP_GROUP_NAME) {
  logError('Missing WORLDCUP_GROUP_NAME env var. See .env.example.');
  process.exit(1);
}

if (!existsSync(LATEST_DIGEST_PATH)) {
  logError(`Digest file not found at ${LATEST_DIGEST_PATH}. ` +
           `Make sure worldcup has produced at least one refresh before running the bot.`);
  process.exit(1);
}

// ── Load digest ──────────────────────────────────────────────────────────────
const digest = readFileSync(LATEST_DIGEST_PATH, 'utf-8').trim();
if (!digest) {
  logError(`Digest file at ${LATEST_DIGEST_PATH} is empty.`);
  process.exit(1);
}

const message = FOOTER ? `${digest}\n${FOOTER}` : digest;

log(`Loaded digest: ${digest.length} chars from ${LATEST_DIGEST_PATH}`);
log(`Target group: "${WORLDCUP_GROUP_NAME}"`);

// ── WhatsApp client ──────────────────────────────────────────────────────────
const client = new Client({
  // clientId 'worldcup' isolates this bot's session from the existing
  // whatsapp-daily-bot. Sessions live under .wwebjs_auth/session-worldcup/
  // (or wherever LocalAuth defaults; the clientId namespaces them).
  authStrategy: new LocalAuth({ clientId: 'worldcup' }),
  puppeteer: { args: ['--no-sandbox'] },
});

client.on('qr', (qr) => {
  log('QR code ready — scan with WhatsApp on your phone (Linked Devices → Link a Device):');
  qrcode.generate(qr, { small: true });
});

client.on('authenticated', () => {
  log('Authenticated — session saved.');
});

client.on('auth_failure', (msg) => {
  logError(`Authentication failed: ${msg}`);
});

client.on('disconnected', (reason) => {
  logError(`Client disconnected: ${reason}`);
});

client.on('ready', async () => {
  log('WhatsApp client ready — sending message…');
  try {
    const chats = await client.getChats();
    const group = chats.find(
      (chat) => chat.isGroup && chat.name === WORLDCUP_GROUP_NAME,
    );

    if (!group) {
      const groups = chats.filter((c) => c.isGroup);
      const groupNames = groups.length
        ? groups.map((c, i) => `  ${i + 1}. ${c.name}`).join('\n')
        : '  (none)';
      logError(
        `Group "${WORLDCUP_GROUP_NAME}" not found.\n` +
        `Available groups (${groups.length}):\n${groupNames}`,
      );
    } else {
      const chat = await client.getChatById(group.id._serialized);
      const sentMsg = await chat.sendMessage(message);

      // Wait for server ACK
      await new Promise((resolveAck) => {
        const timeout = setTimeout(() => {
          log('Warning: ACK timeout after 30s — message may not have been delivered.');
          resolveAck();
        }, 30000);
        client.on('message_ack', (ackMsg, ack) => {
          if (ackMsg.id._serialized === sentMsg.id._serialized && ack >= 1) {
            log(`Server ACK received (ack=${ack}).`);
            clearTimeout(timeout);
            resolveAck();
          }
        });
      });

      log(`Message sent to "${group.name}" (${message.length} chars).`);
    }
  } catch (err) {
    logError(`Failed to send message: ${err.message}`);
  }

  // Grace period for any final ACKs
  await new Promise((r) => setTimeout(r, 2000));
  log('Done — shutting down.');
  await client.destroy();
  process.exit(0);
});

log('Initialising WhatsApp client — waiting for QR or cached session…');
client.initialize();
