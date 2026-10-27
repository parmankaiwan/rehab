// Read-only live-board display verification. Does not start recordings or save samples.
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || 'playwright-core');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = Object.fromEntries((await readFile(path.join(root, 'web/.env.local'), 'utf8')).split(/\r?\n/)
  .filter(line => /^[A-Z_]+=/.test(line)).map(line => { const i = line.indexOf('='); return [line.slice(0, i), line.slice(i + 1).trim().replace(/^['"]|['"]$/g, '')]; }));
const browser = await chromium.launch({ headless: true, executablePath: process.env.FLEXMAP_TEST_CHROMIUM });
try {
  const context = await browser.newContext({ baseURL: 'http://localhost:3000', viewport: { width: 1440, height: 1050 } });
  const login = await context.request.post('/api/master/login', { data: { password: env.MASTER_PASSWORD } });
  if (!login.ok()) throw new Error(`Login failed: ${login.status()}`);
  const page = await context.newPage();
  const errors = [], failures = [];
  let sampleCount = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.url().includes('/api/master/data/emg/') && response.status() >= 400) failures.push(response.status()); });
  page.on('websocket', socket => { if (socket.url().includes('/ws/emg?')) socket.on('framereceived', ({ payload }) => {
    try { const value = JSON.parse(String(payload)); if (value.type === 'emg.samples') sampleCount += value.samples.length; } catch { /* not a JSON frame */ }
  }); });
  await page.goto('/master/live/emg', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('.emg-channel-stat-grid strong').first().waitFor({ timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('.emg-graph-details')?.textContent.includes('displayed samples'), { timeout: 30000 });
  const response = await context.request.get('/api/master/data/emg/status');
  const status = await response.json();
  const canvas = page.getByLabel('Live EMG waveform', { exact: true });
  await canvas.scrollIntoViewIfNeeded();
  const painted = await canvas.evaluate(element => {
    const ctx = element.getContext('2d');
    const { data } = ctx.getImageData(0, 0, element.width, element.height);
    let tracePixels = 0;
    for (let i = 0; i < data.length; i += 4) if (data[i + 1] > 140 && data[i + 2] > 120 && data[i + 1] > data[i] * 1.2) tracePixels++;
    return { width: element.width, height: element.height, tracePixels };
  });
  const result = { checkedAt: new Date().toISOString(), state: status.connection_state, port: status.serial_port,
    channelCount: status.channel_count, rateHz: status.received_rate_hz, invalidPackets: status.invalid_packets,
    isMock: status.is_mock, websocketSampleCount: sampleCount, canvas: painted, pageErrors: errors, emgHttpFailures: failures };
  const pass = response.ok() && result.state === 'STREAMING' && result.isMock === false && result.channelCount === 1 && sampleCount > 100 && painted.tracePixels > 20 && !errors.length && !failures.length;
  result.result = pass ? 'PASS' : 'FAIL';
  const folder = path.join(root, 'data/runtime/live-emg-display');
  await mkdir(folder, { recursive: true });
  await writeFile(path.join(folder, 'verification.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if (!pass) process.exitCode = 1;
} finally { await browser.close(); }
