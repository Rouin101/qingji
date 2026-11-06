import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8781',out='../design/iterations/2026-11-06/backups';await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const ctx=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true}),page=await ctx.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
async function api(data){const r=await ctx.request.post(base+'/api/projects',{data});const p=await r.json();assert(r.ok(),p.error);return p;}
async function get(path){const r=await ctx.request.get(base+path);assert(r.ok());return r.json();}
async function open(p){await page.goto(base);await page.locator('.project-tile').filter({has:page.getByText(p.name,{exact:true})}).click();await page.getByRole('button',{name:'项目备份与恢复',exact:true}).click();}
try {
let p=await api({action:'create',name:'虚构备份验收-'+Date.now(),report:{name:'测试报告',text:'最初的报告正文。'}});
await open(p);const panel=page.locator('.project-backups');
await panel.getByText('还没有本机备份。保存一份后，可以随时下载或恢复。').waitFor();
// Visible failure retains project and permits retry.
await page.route('**/api/projects',r=>r.request().method()==='POST'?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'虚构备份保存失败'})}):r.continue());
await panel.getByRole('button',{name:'保存当前版本备份'}).click();await panel.getByRole('alert').filter({hasText:'虚构备份保存失败'}).waitFor();await page.unroute('**/api/projects');
await panel.getByRole('button',{name:'保存当前版本备份'}).click();await panel.getByText('已保存当前项目版本的本机备份。').waitFor();assert.equal(await panel.locator('li').count(),1);
await panel.getByRole('button',{name:'保存当前版本备份'}).click();await panel.getByText('已保存当前项目版本的本机备份。').waitFor();assert.equal((await get('/api/backups?id='+p.id)).backups.length,1);
const downloadPromise=page.waitForEvent('download');await panel.getByRole('button',{name:'下载备份'}).click();const dl=await downloadPromise;const pack=JSON.parse(await readFile(await dl.path(),'utf8'));assert.equal(pack.payload.project.report.text,'最初的报告正文。');
// A stale window must not label a newer version as the one it backed up.
p=await api({action:'save',id:p.id,version:p.version,changes:{report:{text:'后来保存的新正文。'}}});
await panel.getByRole('button',{name:'保存当前版本备份'}).click();await panel.getByRole('alert').filter({hasText:'项目已更新'}).waitFor();assert.equal((await get('/api/backups?id='+p.id)).backups.length,1);
await open(p);await panel.getByRole('button',{name:'保存当前版本备份'}).click();await panel.getByText('已保存当前项目版本的本机备份。').waitFor();assert.equal(await panel.locator('li').count(),2);
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await panel.screenshot({path:out+'/backups-'+width+'.png'});}
await panel.locator('li').last().getByRole('button',{name:'恢复为副本'}).click();await page.getByRole('heading',{name:p.name+'（交接副本）',exact:true}).waitFor();
const projects=(await get('/api/projects')).projects;const copy=projects.find(x=>x.name===p.name+'（交接副本）');assert(copy);assert.equal((await get('/api/project?id='+copy.id)).report.text,'最初的报告正文。');assert.equal((await get('/api/project?id='+p.id)).report.text,'后来保存的新正文。');
await open(p);await panel.locator('li').first().getByRole('button',{name:'删除备份'}).click();await panel.getByText('已删除这份本机备份。').waitFor();assert.equal(await panel.locator('li').count(),1);
// Unsaved inputs cannot be mislabeled as protected by a project backup.
await page.getByRole('button',{name:'项目概览',exact:true}).click();const form=page.locator('.quick-claim');await form.locator('summary').first().click();await form.locator('textarea').fill('尚未保存的正文');await panel.getByText('请先保存当前输入，再创建备份或恢复副本。').waitFor();assert(await panel.getByRole('button',{name:'保存当前版本备份'}).isDisabled());assert(await panel.getByRole('button',{name:'恢复为副本'}).isDisabled());
assert.deepEqual(errors,[]);const result={status:'passed',checks:['备份失败与重试','重复保存去重','下载完整项目包','旧窗口版本保护','历史列表','恢复副本不覆盖','定向删除','未保存输入保护','390/768/1440布局'],errors};await writeFile(out+'/results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:out+'/failure.png',fullPage:true});console.error(e);process.exitCode=1;}finally{await browser.close();}
