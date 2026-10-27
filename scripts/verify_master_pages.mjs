// Read-only authenticated page/API smoke checks. No capture, recording, or jobs.
import { createRequire } from 'node:module';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.argv[2] || 'playwright-core');
const env = Object.fromEntries((await readFile('web/.env.local','utf8')).split(/\r?\n/).filter(l=>/^[A-Z_]+=/.test(l)).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1).trim().replace(/^['"]|['"]$/g,'')];}));
const routes=['/master','/master/collect','/master/cv-data','/master/emg','/master/live','/master/live/emg','/master/emg/hardware','/master/emg/validation','/master/dataset/cv','/master/dataset/emg','/master/ml/train','/master/ml/datasets','/master/ml/runs','/master/ml/models','/master/ml/emg-comparison','/master/system','/master/sessions'];
const browser=await chromium.launch({headless:true,executablePath:process.env.FLEXMAP_TEST_CHROMIUM});
try{
 const context=await browser.newContext({baseURL:'http://localhost:3000'});
 const login=await context.request.post('/api/master/login',{data:{password:env.MASTER_PASSWORD}});
 if(!login.ok())throw new Error(`Master login HTTP ${login.status()}`);
 const results=[];
 for(const route of routes){
  const page=await context.newPage(),errors=[],apiFailures=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.url().includes('/api/master/data/')&&r.status()>=400){const u=new URL(r.url());apiFailures.push({path:u.pathname.replace(/(?:SMP|REC|EMG|DS|EDS)-[^/]+/g,'[record]'),status:r.status()});}});
  const response=await page.goto(route,{waitUntil:'domcontentloaded',timeout:60000});
  try{await page.waitForLoadState('networkidle',{timeout:6000});}catch{/* Live pages intentionally poll. */}
  const result={route,status:response.status(),pageErrors:errors,apiFailures};
  results.push(result);console.log(JSON.stringify(result));await page.close();
 }
 const report={checkedAt:new Date().toISOString(),results,result:results.every(r=>r.status===200&&!r.pageErrors.length&&!r.apiFailures.length)?'PASS':'FAIL'};
 await mkdir('data/runtime/master-pages',{recursive:true});
 await writeFile('data/runtime/master-pages/verification.json',JSON.stringify(report,null,2));
 if(report.result!=='PASS')process.exitCode=1;
}finally{await browser.close();}
