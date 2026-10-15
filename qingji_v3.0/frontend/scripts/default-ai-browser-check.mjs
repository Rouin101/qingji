import {chromium} from 'playwright-core';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8772', out='../design/iterations/2026-10-15/default-ai';await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
try {
const name='首次核验验收'+Date.now();const response=await page.request.post(base+'/api/projects',{data:{action:'create',name,materials:[{id:'m1',name:'虚构调研报告',text:'本次访谈两位居民。两位居民均表示需要协助。',consent_status:'unconfirmed',enabled:true}]}});assert(response.ok());const p=await response.json();
await page.goto(base);await page.locator('.project-tile').filter({hasText:name}).click();await page.getByRole('button',{name:'结论核验',exact:true}).click();await page.getByRole('heading',{name:'从一份报告开始'}).waitFor();await page.screenshot({path:out+'/review-start.png'});assert.equal(await page.locator('input[type=checkbox]').count(),0);
await page.getByLabel('或使用已保存的材料').selectOption('m1');await page.getByRole('button',{name:'用作待核验报告'}).click();await page.getByText('正文已保存，可以开始核验。').waitFor();const saved=await (await page.request.get(base+'/api/project?id='+p.id)).json();assert.equal(saved.report.text,p.materials[0].text);assert.equal(saved.materials[0].enabled,false);assert.equal(saved.materials[0].consent_status,'confirmed');
await page.getByRole('button',{name:'实践材料',exact:true}).click();await page.locator('.material-intro-art img').waitFor();await page.screenshot({path:out+'/materials.png'});
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:out+'/materials-'+width+'.png'});}
assert.deepEqual(errors,[]);await writeFile(out+'/result.json',JSON.stringify({status:'passed',checks:['首次核验入口','已有材料转报告','原材料保留且排除','默认AI无需勾选','390/768/1440无横向溢出','无页面错误']},null,2));console.log('PASS '+out);
}finally{await browser.close();}
