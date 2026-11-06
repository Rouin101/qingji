import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8782',out='../design/iterations/2026-11-06/questions';await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
async function api(data){const r=await ctx.request.post(base+'/api/projects',{data});const p=await r.json();assert(r.ok(),p.error);return p;}
const overview=()=>page.getByRole('button',{name:'项目概览',exact:true}).click();
try{
let p=await api({action:'create',name:'虚构问题工作区-'+Date.now()});p=await api({action:'practice_brief',id:p.id,version:p.version,brief:{topic:p.name,goal:'保留不同经历'},questions:[{id:'q1',text:'线下有哪些困难？'},{id:'q2',text:'线上有哪些困难？'}],stage:'field'});
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'观察线上操作',question_id:'q2'});const task=p.tasks[0].id;
for(const [q,text]of [['q1','甲窗口记录'],['q2','乙线上记录']])p=await api({action:'practice_observation',id:p.id,version:p.version,observation:{question_id:q,task_id:q==='q2'?task:'',text,finding:text+'发现',uncertainty:text+'疑问',consent_status:'confirmed'}});
await page.goto(base);await page.locator('.project-tile').filter({hasText:p.name}).click();await overview();const w=page.getByRole('region',{name:'问题工作区'});await w.getByLabel('当前实践问题').selectOption('q2');
await w.locator('summary').filter({hasText:'相关行动'}).click();await w.locator('summary').filter({hasText:'阶段发现与来源'}).click();await w.locator('summary').filter({hasText:'仍需了解'}).click();await w.getByText('乙线上记录疑问',{exact:true}).waitFor();assert.equal(await w.getByText('甲窗口记录发现',{exact:true}).count(),0);
await w.getByRole('button',{name:'查看记录与原始来源'}).click();const findings=page.locator('.practice-findings');await findings.locator('[data-observation-id]').waitFor();assert.equal(await findings.locator('[data-observation-id]').count(),1);assert(await findings.locator('.observation-source').evaluate(el=>el.open));await overview();
await w.getByRole('button',{name:'查看这个问题的全部记录'}).click();assert.equal(await findings.getByLabel('筛选记录问题').inputValue(),'q2');await overview();
await w.getByRole('button',{name:'记下这项行动的记录'}).click();const form=page.locator('.practice-record-form');assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),task);await overview();
await w.getByRole('button',{name:'为这个问题记记录'}).click();assert.equal(await form.getByLabel('关联问题',{exact:true}).inputValue(),'q2');assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),'');await form.getByLabel('实际留下的原始记录').fill('新增实际记录');await overview();assert(await w.getByRole('button',{name:'查看最新整理稿'}).isDisabled());
await w.getByLabel('当前实践问题').selectOption('q1');page.once('dialog',d=>d.dismiss());await w.getByRole('button',{name:'为这个问题记记录'}).click();assert.equal(await form.getByLabel('关联问题',{exact:true}).inputValue(),'q2');assert.equal(await form.getByLabel('实际留下的原始记录').inputValue(),'新增实际记录');
await form.getByRole('button',{name:'保存实际记录',exact:true}).click();await form.waitFor({state:'hidden'});await overview();await w.getByLabel('当前实践问题').selectOption('q2');
await w.getByRole('button',{name:'查看最新整理稿'}).click();const preview=w.getByRole('region',{name:'最新实践整理稿'});await preview.waitFor();assert((await preview.innerText()).includes('乙线上记录'));assert(!(await preview.innerText()).includes('甲窗口记录'));const download=page.waitForEvent('download');await preview.getByRole('button',{name:'下载整理稿'}).click();assert((await readFile(await(await download).path(),'utf8')).includes('乙线上记录疑问'));
await w.getByLabel('当前实践问题').selectOption('q1');await preview.waitFor({state:'hidden'});await w.getByRole('button',{name:'查看最新整理稿'}).click();await preview.waitFor();assert((await preview.innerText()).includes('甲窗口记录'));assert(!(await preview.innerText()).includes('乙线上记录'));
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await w.screenshot({path:out+'/questions-'+width+'.png'});}
const current=await(await ctx.request.get(base+'/api/project?id='+p.id)).json();assert.equal(current.report.text,'');assert.equal(current.tasks[0].status,'open');assert.equal(current.lifecycle.observations.at(-1).question_id,'q2');
const stale=await ctx.request.get(base+'/api/practice-report?id='+p.id+'&version=1&question_id=q2');assert.equal(stale.status(),409);
assert.deepEqual(errors,[]);const result={status:'passed',checks:['按问题呈现行动发现疑问','记录精确定位并展开原文','问题筛选联动','行动与问题记录预选','草稿阻止误切换及整理','按问题预览下载且切换清空','不写报告不完成行动','旧版本409','390/768/1440无溢出'],errors};await writeFile(out+'/results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:out+'/failure.png',fullPage:true});console.error(e);process.exitCode=1;}finally{await browser.close();}
