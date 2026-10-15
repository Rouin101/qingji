import test from "node:test";
import assert from "node:assert/strict";
import {reconcileProjectChanges as reconcile} from "../src/project-conflicts.js";

const base={reading_size:16,choices:{},manual_text:null,materials:[{id:"m1",name:"访谈",text:"原文",tags:[],enabled:true}],report:{text:"同句。"},result:{report:{text:"同句。"},issues:[{id:"i1",start:0,end:3,quote:"同句。",suggested_text:"修改。"}]}};
test("different windows can change reading size and add a material without losing either",()=>{
  const remote={...base,materials:[...base.materials,{id:"m2",text:"新记录"}]};
  assert.deepEqual(reconcile(base,{reading_size:18,materials:base.materials},remote),{changes:{reading_size:18},conflicts:[]});
});
test("different metadata edits of the same material merge",()=>{
  const remote={...base,materials:[{...base.materials[0],tags:["社区"]}]};
  const merged=reconcile(base,{materials:[{...base.materials[0],enabled:false}]},remote);
  assert.deepEqual(merged.conflicts,[]);assert.deepEqual(merged.changes.materials,[{...base.materials[0],enabled:false,tags:["社区"]}]);
});
test("a deletion cannot silently remove another author's edit",()=>{
  const remote={...base,materials:[{...base.materials[0],text:"另一页改文"}]};
  assert.deepEqual(reconcile(base,{materials:[]},remote).conflicts,["materials.m1"]);
  assert.deepEqual(reconcile(base,{materials:[]},remote,true).changes,{materials:[]});
});
test("choosing one overlapping value preserves unrelated remote edits",()=>{
  const remote={...base,materials:[{...base.materials[0],text:"远端正文",tags:["新标签"]}]};
  const local={materials:[{...base.materials[0],text:"本页正文",enabled:false}]};
  const keep=reconcile(base,local,remote,true);
  assert.deepEqual(keep.conflicts,["materials.m1.text"]);
  assert.deepEqual(keep.changes.materials,[{...base.materials[0],text:"本页正文",enabled:false,tags:["新标签"]}]);
});
test("old issue choices after a recheck become a manual draft only by explicit choice",()=>{
  const remote={...base,result:{report:{text:"新句。"},issues:[]},report:{text:"新句。"}};
  const local={choices:{i1:"accepted"},manual_text:null};
  assert.deepEqual(reconcile(base,local,remote).conflicts,["author_text"]);
  assert.deepEqual(reconcile(base,local,remote).changes,{});
  assert.deepEqual(reconcile(base,local,remote,true).changes,{manual_text:"修改。"});
});
test("whole concurrent report replacement never mixes name and body",()=>{
  const before={...base,report:{name:"旧文",text:"旧内容"}};
  const remote={...before,report:{name:"远端文件",text:"远端内容"}};
  const local={report:{name:"本页文件",text:"本页内容"}};
  assert.deepEqual(reconcile(before,local,remote,true),{changes:local,conflicts:["report"]});
});
