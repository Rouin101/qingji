import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8775',out='../design/iterations/2026-10-22/report';await mkdir(out,{recursive:true});
const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const ctx=await b.newContext({viewport:{width:1440,height:1000}}),page=await ctx.newPage();page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function api(data){const r=await ctx.request.post(base+'/api/projects',{data});const p=await r.json();assert(r.ok(),p.error);return p;}
let p;
try{
p=await api({action:'create',name:'虚构记录回看-'+Date.now()});p=await api({action:'practice_brief',id:p.id,version:p.version,brief:{topic:p.name,goal:'区分不同对象和材料'},questions:[{id:'q1',text:'线下办理有哪些经历？'},{id:'q2',text:'线上办理有哪些经历？'}],stage:'field'});
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'访谈线下对象',question_id:'q1'});const t1=p.tasks[0].id;
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'观察线上对象',question_id:'q2'});const t2=p.tasks[1].id;
for(const [question_id,task_id,text,finding] of [['q1',t1,'甲独立办理，原文甲。','线下个体反馈'],['q2',t2,'乙需要协助，原文乙。','线上个体反馈'],['q1','','已移除原文不应显示','保留的旧备注']])p=await api({action:'practice_observation',id:p.id,version:p.version,observation:{question_id,task_id,text,finding,uncertainty:'范围有限',consent_status:'confirmed',source_role:'受访者陈述'}});
p=await api({action:'save',id:p.id,version:p.version,changes:{materials:p.materials.slice(0,2).map((m,i)=>({...m,name:'同名访谈记录',enabled:i===0,text:i===0?'甲独立办理，更新后的原文甲。':m.text}))}});const version=p.version;
await page.goto(base);await page.locator('.project-tile').filter({hasText:p.name}).click();await page.getByRole('button',{name:'行动与记录',exact:true}).click();
await page.getByRole('button',{name:'查看最新整理稿',exact:true}).click();
const preview=page.getByRole('region',{name:'最新实践整理稿'});await preview.waitFor();
const text=await preview.locator('pre').innerText();assert(text.includes('更新后的原文甲'));assert(text.includes('需要重新核对'));assert(!text.includes('原文乙'));assert(!text.includes('已移除原文不应显示'));
const downloadPromise=page.waitForEvent('download');await preview.getByRole('button',{name:'下载整理稿'}).click();const download=await downloadPromise;const stream=await download.createReadStream();const chunks=[];for await(const chunk of stream)chunks.push(chunk);assert.equal(Buffer.concat(chunks).toString('utf8'),text);
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});await preview.scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await preview.screenshot({path:out+'/report-'+width+'.png'});}
await page.getByRole('button',{name:'记下实际发现',exact:true}).click();await page.locator('.practice-record-form textarea[name="text"]').fill('未保存的记录');assert(await page.getByRole('button',{name:'查看最新整理稿'}).isDisabled());assert(await preview.getByRole('button',{name:'下载整理稿'}).isDisabled());
let after=await(await ctx.request.get(base+'/api/project?id='+p.id)).json();assert.equal(after.version,version);
p=await api({action:'save',id:p.id,version:p.version,changes:{report:{name:'团队报告',text:'团队已经撰写的报告，不可覆盖。'}}});
assert.equal((await ctx.request.get(base+'/api/practice-report?id='+p.id+'&version='+version)).status(),409);
assert.equal((await ctx.request.get(base+'/api/practice-report?id='+p.id+'&version=no')).status(),400);
page.on('dialog',d=>d.accept());await page.reload();await page.locator('.project-tile').filter({hasText:p.name}).click();await page.getByRole('button',{name:'行动与记录',exact:true}).click();await page.getByRole('button',{name:'查看最新整理稿'}).click();await preview.waitFor();assert.equal(await page.getByRole('button',{name:'整理为报告初稿',exact:true}).count(),0);
after=await(await ctx.request.get(base+'/api/project?id='+p.id)).json();assert.equal(after.version,p.version);assert.deepEqual(after.report,p.report);assert.deepEqual(errors,[]);
const result={status:'passed',checks:['来源更新提示','排除与移除材料不导出','下载与预览一致','草稿阻止整理','只读且保留已有报告','旧版本409与非法版本400','390/768/1440布局'],errors};await writeFile(out+'/results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:out+'/failure.png',fullPage:true});console.error(e);process.exitCode=1;}finally{await b.close();}
