import test from "node:test";
import assert from "node:assert/strict";
import {reconcileIssueSelection} from "../src/review-filter-helpers.js";

test("author decisions continue in report order while deliberate collapse stays closed", () => {
  const before = ["a","b","c","d"].map(id=>({id}));
  assert.equal(reconcileIssueSelection(before,[before[0],before[2],before[3]],"b"),"c");
  assert.equal(reconcileIssueSelection(before,[before[0],before[2]],"d"),"c");
  assert.equal(reconcileIssueSelection(before,[],"a"),null);
  assert.equal(reconcileIssueSelection(before,before,null),null);
  assert.equal(reconcileIssueSelection(before,[{id:"new"}],"b"),"new");
});
import {
  filterIssues,
  isIssueVisible,
  getNavPosition,
  computeFilterCounts,
} from "../src/review-filter-helpers.js";

const sampleIssues = [
  { id: "i-sup", quote: "结论1", support_status: "supported", category: "其他" },
  { id: "i-part", quote: "结论2", support_status: "partial", category: "范围外推" },
  { id: "i-unsup", quote: "结论3", support_status: "unsupported", category: "范围外推" },
  { id: "i-dis", quote: "结论4", support_status: "disagreement", category: "来源表述" },
  { id: "i-pend", quote: "结论5", support_status: "pending", category: "数字口径" },
];

test("filterIssues: 'all' returns complete set without modifications", () => {
  const result = filterIssues(sampleIssues, "all");
  assert.equal(result.length, 5);
  assert.deepEqual(result, sampleIssues);
});

test("filterIssues: 'pending' includes all undecided reviewable issues and excludes supported", () => {
  const pendingInitial = filterIssues(sampleIssues, "pending", {});
  assert.equal(pendingInitial.length, 4);
  assert.ok(!pendingInitial.some((i) => i.id === "i-sup"), "supported issue must NOT be in pending");
  assert.ok(pendingInitial.some((i) => i.id === "i-part"));
  assert.ok(pendingInitial.some((i) => i.id === "i-unsup"));
  assert.ok(pendingInitial.some((i) => i.id === "i-dis"));
  assert.ok(pendingInitial.some((i) => i.id === "i-pend"));
});

test("filterIssues: author choice 'kept' or 'accepted' removes issue from 'pending' without upgrading support", () => {
  const choices = { "i-unsup": "kept", "i-part": "accepted" };
  const pendingAfterChoices = filterIssues(sampleIssues, "pending", choices);
  assert.equal(pendingAfterChoices.length, 2);
  assert.ok(!pendingAfterChoices.some((i) => i.id === "i-unsup"), "kept issue resolved from pending queue");
  assert.ok(!pendingAfterChoices.some((i) => i.id === "i-part"), "accepted issue resolved from pending queue");

  // Filtering by original status still finds the issue with unchanged support status
  const unsupportedOnly = filterIssues(sampleIssues, "unsupported", choices);
  assert.equal(unsupportedOnly.length, 1);
  assert.equal(unsupportedOnly[0].id, "i-unsup");
  assert.equal(unsupportedOnly[0].support_status, "unsupported");
});

test("filterIssues: specific status filtering", () => {
  assert.equal(filterIssues(sampleIssues, "supported").length, 1);
  assert.equal(filterIssues(sampleIssues, "partial").length, 1);
  assert.equal(filterIssues(sampleIssues, "unsupported").length, 1);
  assert.equal(filterIssues(sampleIssues, "disagreement").length, 1);
  assert.equal(filterIssues(sampleIssues, "pending_verify").length, 1);
});

test("getNavPosition: handles empty, single, middle, and boundaries", () => {
  // Empty
  const emptyNav = getNavPosition([], null);
  assert.equal(emptyNav.label, "0 / 0");
  assert.equal(emptyNav.canPrev, false);
  assert.equal(emptyNav.canNext, false);

  // Single
  const single = [{ id: "one" }];
  const singleNav = getNavPosition(single, "one");
  assert.equal(singleNav.label, "1 / 1");
  assert.equal(singleNav.canPrev, false);
  assert.equal(singleNav.canNext, false);

  // Three items
  const three = [{ id: "a" }, { id: "b" }, { id: "c" }];

  // None active
  const unselectedNav = getNavPosition(three, null);
  assert.equal(unselectedNav.label, "-- / 3");
  assert.equal(unselectedNav.canPrev, false);
  assert.equal(unselectedNav.canNext, true);
  assert.equal(unselectedNav.nextId, "a");

  // First item active
  const firstNav = getNavPosition(three, "a");
  assert.equal(firstNav.label, "1 / 3");
  assert.equal(firstNav.canPrev, false);
  assert.equal(firstNav.canNext, true);
  assert.equal(firstNav.nextId, "b");

  // Second item active
  const midNav = getNavPosition(three, "b");
  assert.equal(midNav.label, "2 / 3");
  assert.equal(midNav.canPrev, true);
  assert.equal(midNav.canNext, true);
  assert.equal(midNav.prevId, "a");
  assert.equal(midNav.nextId, "c");

  // Last item active
  const lastNav = getNavPosition(three, "c");
  assert.equal(lastNav.label, "3 / 3");
  assert.equal(lastNav.canPrev, true);
  assert.equal(lastNav.canNext, false);
  assert.equal(lastNav.prevId, "b");
});

test("computeFilterCounts: accurately computes all tabs", () => {
  const choices = { "i-unsup": "kept" };
  const counts = computeFilterCounts(sampleIssues, choices);
  assert.equal(counts.all, 5);
  assert.equal(counts.pending, 3); // 4 non-supported minus 1 kept = 3
  assert.equal(counts.supported, 1);
  assert.equal(counts.partial, 1);
  assert.equal(counts.unsupported, 1);
  assert.equal(counts.disagreement, 1);
  assert.equal(counts.pending_verify, 1);
});
