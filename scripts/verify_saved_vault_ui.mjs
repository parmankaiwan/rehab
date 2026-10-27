// Verify synthetic cloud fixtures through the actual authenticated website.
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || 'playwright-core');
const reportPath = process.argv[3];
if (!reportPath) throw new Error('Supply a synthetic acceptance report path');
const report = JSON.parse(await readFile(reportPath, 'utf8'));
if (!report.fixtures_excluded_from_training) throw new Error('Expected excluded synthetic fixtures');
const env = Object.fromEntries((await readFile('web/.env.local', 'utf8')).split(/\r?\n/).filter(l => /^[A-Z_]+=/.test(l)).map(l => { const i=l.indexOf('='); return [l.slice(0,i),l.slice(i+1).trim().replace(/^['"]|['"]$/g,'')]; }));
const browser = await chromium.launch({ headless:true, executablePath:process.env.FLEXMAP_TEST_CHROMIUM });
try {
 const context = await browser.newContext({baseURL:'http://localhost:3000'});
 const login = await context.request.post('/api/master/login',{data:{password:env.MASTER_PASSWORD}});
 if(!login.ok()) throw new Error(`Login HTTP ${login.status()}`);
 const page = await context.newPage(); const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`/master/dataset/${report.cv.sample_id}`,{waitUntil:'domcontentloaded'});
 const image=page.getByAltText('Clean captured sample');
 await image.waitFor({timeout:30000});
 await image.evaluate(img=>img.decode());
 const cvImage=await image.evaluate(img=>({complete:img.complete,width:img.naturalWidth,height:img.naturalHeight}));
 await page.goto(`/master/dataset/emg/${report.emg.recording_id}`,{waitUntil:'domcontentloaded'});
 const waveform=page.getByRole('img',{name:'Waveform for channel_1'});
 await waveform.waitFor({timeout:30000});
 const pointCount=(await waveform.locator('polyline').getAttribute('points')).trim().split(/\s+/).length;
 const result={cvImage,emgWaveformPointCount:pointCount,pageErrors:errors,result:cvImage.complete&&cvImage.width>0&&pointCount===3&&!errors.length?'PASS':'FAIL'};
 await writeFile(reportPath.replace(/\.json$/,'.ui.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));
 if(result.result!=='PASS')process.exitCode=1;
} finally {await browser.close();}
