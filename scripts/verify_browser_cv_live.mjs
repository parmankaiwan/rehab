// Real browser camera check: no fake-media flags, no frames/recordings saved.
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || 'playwright-core');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = Object.fromEntries((await readFile(path.join(root, 'web/.env.local'), 'utf8')).split(/\r?\n/).filter(line => /^[A-Z_]+=/.test(line)).map(line => { const i = line.indexOf('='); return [line.slice(0, i), line.slice(i + 1).trim().replace(/^['"]|['"]$/g, '')]; }));
const browser = await chromium.launch({ headless: true, executablePath: process.env.FLEXMAP_TEST_CHROMIUM });
try {
  const context = await browser.newContext({ baseURL: 'http://localhost:3000', permissions: ['camera'], viewport: { width: 1440, height: 1000 } });
  const login = await context.request.post('/api/master/login', { data: { password: env.MASTER_PASSWORD } });
  if (!login.ok()) throw new Error(`Master login failed: ${login.status()}`);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/master/live/cv', { waitUntil: 'domcontentloaded', timeout: 60000 });
  // Do not click a source button: opening CV Live must start browser capture.
  await page.waitForFunction(() => Array.from(document.querySelectorAll('dt')).some(dt => dt.textContent === 'Source' && dt.nextElementSibling?.textContent === 'BROWSER MEDIAPIPE'), undefined, { timeout: 10000 });
  let readiness = 'NOT_READY';
  try {
    await page.waitForFunction(() => {
      const video = document.querySelector('video');
      const metrics = Object.fromEntries(Array.from(document.querySelectorAll('dt')).map(dt => [dt.textContent, dt.nextElementSibling?.textContent]));
      return video?.videoWidth > 0 && video.readyState >= 2 && metrics['Pose model']?.startsWith('READY') && Number(metrics['Inference results']) >= 2;
    }, undefined, { timeout: 45000 });
    readiness = 'CAMERA_AND_MEDIAPIPE_VERIFIED';
  } catch { /* Report actual failure below, never substitute fake capture. */ }
  const observed = await page.evaluate(() => {
    const video = document.querySelector('video');
    const tracks = video?.srcObject instanceof MediaStream ? video.srcObject.getVideoTracks() : [];
    return { width: video?.videoWidth || 0, height: video?.videoHeight || 0,
      mediaTime: video?.currentTime || 0, liveTracks: tracks.filter(t => t.readyState === 'live').length,
      system: Array.from(document.querySelectorAll('dt')).map(dt => [dt.textContent, dt.nextElementSibling?.textContent]),
      alerts: Array.from(document.querySelectorAll('.live-warning')).map(e => e.textContent) };
  });
  await page.goto('/master', { waitUntil: 'domcontentloaded' }); // release camera
  const result = { checkedAt: new Date().toISOString(), readiness, automaticBrowserStartup: true, observed, pageErrors: errors, fakeMedia: false, savedFrames: false };
  const folder = path.join(root, 'data/runtime/browser-cv-live');
  await mkdir(folder, { recursive: true });
  await writeFile(path.join(folder, 'verification.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if (readiness !== 'CAMERA_AND_MEDIAPIPE_VERIFIED' || errors.length) process.exitCode = 1;
} finally { await browser.close(); }
