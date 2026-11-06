import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8784',out='../design/iterations/2026-11-06/followups';await mkdir(out,{recursive:true});
const b=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true}),ctx=await b.newContext({viewport:{width:1440,height:1000}}),page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
async function api(data){const r=await ctx.request.post(base+'/api/projects',{data});const p=await r.json();assert(r.ok(),p.error);return p;}
let p;
async function current(){return(await ctx.request.get(base+'/api/project?id='+p.id)).json();}
async function open(){await page.goto(base);await page.locator('.project-tile').filter({hasText:p.name}).click();await page.getByRole('button',{name:'项目概览',exact:true}).click();}
const w=page.getByRole('region',{name:'问题工作区'}),form=page.getByRole('form',{name:'确认后续行动'});
async function recordOrigin(){await w.locator('summary').filter({hasText:'仍需了解的情况'}).click();await w.getByRole('button',{name:'为这条疑问安排行动'}).click();}
try{
p=await api({action:'create',name:'虚构后续行动-'+Date.now()});p=await api({action:'practice_brief',id:p.id,version:p.version,brief:{topic:p.name,goal:'了解后续变化'},questions:[{id:'q1',text:'需要哪些帮助？'}],stage:'field'});p=await api({action:'practice_observation',id:p.id,version:p.version,observation:{question_id:'q1',text:'甲在最后一步需要帮助。',uncertainty:'之后能否独立完成？',consent_status:'confirmed'}});
await open();await recordOrigin();await form.getByLabel('后续行动安排').fill('联系甲了解后续使用经历');await form.getByLabel('行动截止日期').fill('2026-12-01');await form.getByLabel('行动补充说明').fill('先约定方便的时间');await form.getByText('草稿已备份到此浏览器，尚未保存到项目。恢复不会自动调用 AI。',{exact:true}).waitFor();assert.equal((await current()).tasks.length,0);
await open();await recordOrigin();await form.getByRole('button',{name:'恢复这份草稿'}).click();assert.equal(await form.getByLabel('后续行动安排').inputValue(),'联系甲了解后续使用经历');
await page.route('**/api/projects',r=>r.request().method()==='POST'?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'虚构保存失败'})}):r.continue());await form.getByRole('button',{name:'确认创建后续行动'}).click();await form.getByRole('alert').filter({hasText:'虚构保存失败'}).waitFor();await page.unroute('**/api/projects');await form.getByRole('button',{name:'确认创建后续行动'}).click();await form.waitFor({state:'hidden'});p=await current();assert.equal(p.tasks.length,1);assert.equal(p.tasks[0].status,'open');assert.equal(p.tasks[0].due_date,'2026-12-01');assert.equal(p.lifecycle.task_links[p.tasks[0].id],'q1');assert.equal(p.materials.length,1);assert.equal(p.lifecycle.observations.length,1);assert(p.tasks[0].notes.includes('之后能否独立完成'));
// Existing-source protection survives a successful save and retry.
await w.getByRole('button',{name:'为这条疑问安排行动'}).click();await form.getByRole('button',{name:'确认创建后续行动'}).click();await form.getByRole('alert').filter({hasText:'已安排过行动'}).waitFor();await form.getByRole('button',{name:'放弃这份行动草稿'}).click();
await page.route('**/api/question-synthesis',r=>{const o=p.lifecycle.observations[0];return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:p.version,question_id:'q1',analysis:{findings:[],differences:[],questions:[{text:'其他操作环节是否也需要帮助？',citations:[{observation_id:o.id,material_id:o.material_id,quote:'甲在最后一步需要帮助。'}]}],limits:['不能外推']}})});});
await w.getByRole('button',{name:'用 AI 整理阶段发现'}).click();await w.getByRole('button',{name:'据此起草后续行动'}).click();await form.getByLabel('后续行动安排').fill('了解其他操作环节');
for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await form.screenshot({path:out+'/followup-'+width+'.png'});}
await form.getByRole('button',{name:'确认创建后续行动'}).click();await form.waitFor({state:'hidden'});p=await current();assert.equal(p.tasks.length,2);assert(p.tasks[1].notes.includes('其他操作环节'));assert.equal(p.tasks[1].status,'open');
await w.locator('summary').filter({hasText:'相关行动'}).click();await w.getByRole('button',{name:'记下这项行动的记录'}).last().click();const record=page.locator('.practice-record-form').filter({has:page.locator('textarea[name="text"]')});assert.equal(await record.getByLabel('对应行动',{exact:true}).inputValue(),p.tasks[1].id);assert.equal(await record.getByLabel('关联问题',{exact:true}).inputValue(),'q1');
assert.deepEqual(errors,[]);const result={status:'passed',mocked_analysis:true,checks:['团队疑问起草','未提交不写数据','草稿恢复','失败保留重试','保存关联与来源日期','重复来源拒绝','AI疑问确认成行动','行动接实际记录','三种屏宽'],errors};await writeFile(out+'/results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){await page.screenshot({path:out+'/failure.png',fullPage:true});console.error(e);process.exitCode=1;}finally{await b.close();}
