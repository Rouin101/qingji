import {chromium} from 'playwright-core';
import {readdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const root=path.resolve('../output/evaluations');
let folder;
for(const name of (await readdir(root)).sort().reverse()){
  const candidate=path.join(root,name);
  const result=JSON.parse(await readFile(path.join(candidate,'results.json'),'utf8'));
  if(result.mode==='replay'){folder=candidate;break;}
}
assert.ok(folder,'Run the model-free evaluation first');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const errors=[],external=[];
try{
  const page=await browser.newPage({acceptDownloads:true});
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(/^https?:/.test(request.url()))external.push(request.url());});
  await page.goto(pathToFileURL(path.join(folder,'review.html')).href);
  assert.equal(await page.locator('section').count(),6);
  assert.deepEqual(await page.locator('select').evaluateAll(nodes=>nodes.map(n=>n.value)),Array(6).fill('pending'));
  for(const width of [390,768,1440]){
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
    await page.screenshot({path:path.join(folder,`review-${width}.png`),fullPage:false});
  }
  await page.locator('select').first().selectOption('fail');
  await page.getByRole('button',{name:'下载人工复核记录'}).click();
  await page.getByRole('status').filter({hasText:'请填写依据'}).waitFor();
  await page.locator('textarea').first().fill('浏览器测试：受控回放没有分析两类不同经历；不是模型评分。');
  const downloading=page.waitForEvent('download');
  await page.getByRole('button',{name:'下载人工复核记录'}).click();
  const download=await downloading;
  const review=JSON.parse(await readFile(await download.path(),'utf8'));
  const original=JSON.parse(await readFile(path.join(folder,'results.json'),'utf8'));
  assert.equal(review.run_hash,original.run_hash);
  assert.equal(review.mode,'replay');
  assert.equal(review.cases[0].verdict,'fail');
  assert.equal(review.cases[0].response_hash,original.cases[0].response_hash);
  assert.ok(review.cases.slice(1).every(c=>c.verdict==='pending'));
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  await writeFile(path.join(folder,'browser-check.json'),JSON.stringify({checks:6,errors,external,widths:[390,768,1440]},null,2));
  console.log(JSON.stringify({checks:6,errors,external,folder}));
}finally{await browser.close();}
