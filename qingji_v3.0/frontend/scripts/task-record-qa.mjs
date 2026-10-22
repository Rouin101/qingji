import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8774',out='../design/iterations/2026-10-22/task-record';await mkdir(out,{recursive:true});
const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const ctx=await b.newContext({viewport:{width:1440,height:1000}}),page=await ctx.newPage();page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function api(data){const r=await ctx.request.post(base+'/api/projects',{data});const p=await r.json();assert(r.ok(),p.error);return p;}
let p;
try{
p=await api({action:'create',name:'虚构行动记录入口-'+Date.now()});p=await api({action:'practice_brief',id:p.id,version:p.version,brief:{topic:p.name,goal:'保留不同场景的实际经历'},questions:[{id:'q1',text:'窗口办理有哪些困难？'},{id:'q2',text:'线上操作有哪些困难？'}],stage:'field'});
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'走访线下服务窗口',question_id:'q1'});const first=p.tasks[0].id;
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'观察线上操作过程',question_id:'q2'});const second=p.tasks[1].id;
p=await api({action:'create_task',id:p.id,version:p.version,action_text:'尚未关联问题的安排'});
await page.goto(base);await page.locator('.project-tile').filter({hasText:p.name}).click();await page.getByRole('button',{name:'行动与记录',exact:true}).click();
const firstCard=page.locator('.task-card').filter({hasText:'走访线下服务窗口'}),secondCard=page.locator('.task-card').filter({hasText:'观察线上操作过程'}),form=page.locator('.practice-record-form');
const open=card=>card.getByRole('button',{name:'记下这项行动的发现',exact:true}).click();
assert.equal(await page.locator('.task-card').filter({hasText:'尚未关联问题的安排'}).getByRole('button',{name:'记下这项行动的发现'}).count(),0);
await open(secondCard);assert.equal(await form.getByLabel('关联问题',{exact:true}).inputValue(),'q2');assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),second);assert(await form.getByLabel('实际留下的原始记录').evaluate(el=>el===document.activeElement));await form.getByLabel('实际留下的原始记录').fill('虚构：乙在第二步需要帮助。');await form.getByLabel('团队的阶段发现').fill('仅描述本次观察。');await open(secondCard);assert.equal(await form.getByLabel('实际留下的原始记录').inputValue(),'虚构：乙在第二步需要帮助。');
page.once('dialog',d=>d.dismiss());await open(firstCard);assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),second);assert.equal(await form.getByLabel('团队的阶段发现').inputValue(),'仅描述本次观察。');
await page.getByRole('button',{name:'实践指导',exact:true}).click();await page.getByRole('button',{name:'行动与记录',exact:true}).click();assert.equal(await form.getByLabel('实际留下的原始记录').inputValue(),'虚构：乙在第二步需要帮助。');
page.once('dialog',d=>d.accept());await open(firstCard);assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),first);assert.equal(await form.getByLabel('实际留下的原始记录').inputValue(),'');await form.getByLabel('实际留下的原始记录').fill('虚构：甲独立办理完成。');
const response=page.waitForResponse(r=>r.url().endsWith('/api/projects')&&r.request().postDataJSON()?.action==='practice_observation');await form.getByRole('button',{name:'保存实际记录',exact:true}).click();const res=await response;p=await res.json();assert(res.ok(),p.error);assert.equal(p.lifecycle.observations[0].task_id,first);assert.equal(p.lifecycle.observations[0].question_id,'q1');assert.equal(p.tasks.find(t=>t.id===first).status,'open');
await form.waitFor({state:'hidden'});await open(secondCard);assert.equal(await form.getByLabel('对应行动',{exact:true}).inputValue(),second);assert.equal(await form.getByLabel('实际留下的原始记录').inputValue(),'');
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});await form.scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:out+'/record-'+width+'.png',fullPage:true});}
assert.deepEqual(errors,[]);const result={status:'passed',checks:['任务入口预选问题与行动并定位正文','同一行动保留草稿','拒绝切换时保留全部记录','项目分区切换保留草稿','确认换行动后重置输入','保存精确关联且不完成任务','下一条记录不残留旧内容','无问题任务不提供误导入口','390/768/1440无溢出'],errors};await writeFile(out+'/results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:out+'/failure.png',fullPage:true});console.error(e);process.exitCode=1;}finally{await b.close();}
