import test from "node:test";
import assert from "node:assert/strict";
import {changedText, highlightedLines} from "../src/review-state.js";

test("Unicode replacement preserves later Chinese text and emoji", () => {
  const source = "🙂同句。\n同句。";
  const issues = [{id:"a",start:1,end:4,quote:"同句。",suggested_text:"记录明确。"},
    {id:"b",start:5,end:8,quote:"同句。",suggested_text:"另一记录。"}];
  const changed = changedText(source, issues, {a:"accepted"});
  assert.equal(changed, "🙂记录明确。\n同句。");
  const marks = highlightedLines(changed, issues, {a:"accepted"}, "b").flatMap((line) => line.parts).filter((part) => part.issue);
  assert.equal(marks.length, 1);
  assert.equal(marks[0].issue.id, "b");
  assert.equal(marks[0].text, "同句。");
});

test("overlapping accepted changes are rejected instead of silently overwriting", () => {
  const issues = [{id:"a",start:0,end:4,quote:"同句。后",suggested_text:"替换。"},
    {id:"b",start:0,end:3,quote:"同句。",suggested_text:"修改。"}];
  assert.throws(() => changedText("同句。后文", issues, {a:"accepted",b:"accepted"}));
});

test("keeping an original sentence does not modify it", () => {
  const issue = {id:"a",start:0,end:3,quote:"同句。",suggested_text:"修改。"};
  assert.equal(changedText("同句。", [issue], {a:"kept"}), "同句。");
});
