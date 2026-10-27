// Headless browser acceptance. Pass the installed playwright-core module path.
import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium}=require(process.argv[2]||'playwright-core');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const config=Object.fromEntries((await readFile(path.join(root,'web','.env.local'),'utf8')).split(/\r?\n/).filter(l=>/^[A-Z_]+=/.test(l)).map(l=>{const i=l.indexOf('=');return [l.slice(0,i),l.slice(i+1).trim().replace(/^['"]|['"]$/g,'')]}));
const browser=await chromium.launch({headless:true,executablePath:process.env.FLEXMAP_TEST_CHROMIUM});
try{
 const context=await browser.newContext({baseURL:'http://localhost:3000',viewport:{width:1440,height:1050}});const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:3000/master/ml/emg-comparison',{waitUntil:'domcontentloaded',timeout:60000});
 if(await page.locator('#master-password').count()){
  if(!config.MASTER_PASSWORD)throw new Error('Master browser-test credential is missing');
  const login=await context.request.post('http://localhost:3000/api/master/login',{data:{password:config.MASTER_PASSWORD}});
  if(!login.ok())throw new Error('Master test login failed: '+login.status());
  await page.reload({waitUntil:'networkidle'});
 }
 await page.getByRole('tab',{name:'Gaussian Quadrature Optimization'}).waitFor({timeout:60000});
 await page.waitForFunction(()=>Array.from(document.querySelectorAll('option')).some(option=>option.textContent==='MOVING_PEAK'));
 // Bounded UI run on the same API/worker path used by the study controls.
 await page.getByRole('button',{name:'Run Study A',exact:true}).click();
 await page.getByText(/Dataset SPATIAL-ENVELOPE-V2/).waitFor({timeout:120000});
 const A={activity:await page.getByRole('img',{name:'Estimated versus reference activity'}).count(),heatmap:await page.getByRole('img',{name:'Spatial reference field heatmap'}).count(),exports:await page.locator('a[href*="/figures/study_a"]').count()};
 for(const anchor of await page.locator('a[href*="/figures/study_a"]').all()){
  const r=await context.request.get(await anchor.getAttribute('href'));if(r.status()!==200)throw new Error('Figure download failed: '+r.status());
 }
 await page.getByRole('tab',{name:'Mathematics-Informed Learning'}).click();
 await page.getByRole('button',{name:'Run Study B',exact:true}).click();
 await page.getByRole('img',{name:'Learned spatial weights'}).waitFor({timeout:120000});
 const B={weights:await page.getByRole('img',{name:'Learned spatial weights'}).count(),loss:await page.getByRole('img',{name:'Training and validation loss',exact:true}).count()};
 await page.getByRole('tab',{name:'Multichannel Test Device'}).click();
 await page.getByRole('button',{name:'Run TEST DEVICE',exact:true}).click();
 await page.getByRole('img',{name:'TEST DEVICE waveform'}).waitFor({timeout:30000});
 const folder=path.join(root,'data','runtime','browser-research');await mkdir(folder,{recursive:true});await page.screenshot({path:path.join(folder,'research-dashboard.png'),fullPage:true});
 const result={status:errors.length?'FAIL':'PASS',A,B,testDeviceWaveform:true,pageErrors:errors};await writeFile(path.join(folder,'browser-report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 if(errors.length)process.exitCode=1;
}finally{await browser.close();}
