import test from 'node:test';
import assert from 'node:assert/strict';
import {candidateBlock,appendCandidate} from '../src/synthesis-draft.js';
const project={version:2,lifecycle:{questions:[{id:'q1',text:'哪些困难？'}],observations:[{id:'o1',material_id:'m1',question_id:'q1'}]},materials:[{id:'m1',name:'访谈',enabled:true,consent_status:'confirmed'}]};
const item={text:'仅为候选',citations:[{observation_id:'o1',material_id:'m1',quote:'原话'}]},result={version:2,question_id:'q1',analysis:{findings:[item],limits:['不代表总体']}};
test('candidate includes source identifiers, quote and limits without changing report',()=>{
 const block=candidateBlock(project,result,'findings',item);
 for(const text of ['待核对','访谈','m1','o1','原话','不代表总体'])assert(block.includes(text));
 assert.equal(appendCandidate('作者原文',block),'作者原文\n\n'+block);
 assert.equal(appendCandidate('',block),block);
});
test('old versions and changed source scope cannot be staged',()=>{
 assert.throws(()=>candidateBlock(project,{...result,current:false},'findings',item));
 assert.throws(()=>candidateBlock({...project,version:3},result,'findings',item));
 assert.throws(()=>candidateBlock({...project,materials:[]},result,'findings',item));
 assert.throws(()=>candidateBlock(project,result,'findings',{...item}));
});
test('overflow refuses instead of truncating either current text or candidate',()=>{
 assert.equal(appendCandidate('甲'.repeat(23997),'乙').length,24000);
 assert.throws(()=>appendCandidate('甲'.repeat(23998),'乙'),/不会截断/);
});
