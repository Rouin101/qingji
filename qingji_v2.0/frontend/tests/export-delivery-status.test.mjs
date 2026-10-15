import test from "node:test";
import assert from "node:assert/strict";
import { changedText } from "../src/review-state.js";
import {
  isImportedUnverified,
  computeAuthorChoices,
  computeStatusBadge,
  formatMaterialScope,
  computeSummaryBanner,
} from "../src/export-status-helpers.js";

// Unit tests for export menu delivery check state presentation and data integrity

test("accepted suggested edit updates displayed text and marks text as pending recheck", () => {
  const original = "所有居民都需要帮助。";
  const issues = [
    {
      id: "i1",
      start: 0,
      end: 10,
      quote: "所有居民都需要帮助。",
      suggested_text: "本次受访的三位居民均提出生活帮助需求。",
      support_status: "unsupported",
    },
  ];
  const choices = { i1: "accepted" };
  const displayText = changedText(original, issues, choices);
  assert.equal(displayText, "本次受访的三位居民均提出生活帮助需求。");
  assert.notEqual(displayText, original);
});

test("kept original sentence preserves text without upgrading support status", () => {
  const original = "所有居民都需要帮助。";
  const issues = [
    {
      id: "i1",
      start: 0,
      end: 10,
      quote: "所有居民都需要帮助。",
      suggested_text: "本次受访的三位居民均提出生活帮助需求。",
      support_status: "unsupported",
    },
  ];
  const choices = { i1: "kept" };
  const displayText = changedText(original, issues, choices);
  assert.equal(displayText, original);
  // Author kept original sentence, but support_status remains unsupported
  assert.equal(issues[0].support_status, "unsupported");
});

test("supported claim requires no rewrite and displayText remains identical", () => {
  const original = "访谈对象提到了用水困难。";
  const issues = [
    {
      id: "i2",
      start: 0,
      end: 12,
      quote: "访谈对象提到了用水困难。",
      suggested_text: null,
      support_status: "supported",
    },
  ];
  const choices = {};
  const displayText = changedText(original, issues, choices);
  assert.equal(displayText, original);
});

test("computeAuthorChoices correctly calculates choices for reviewable issues and excludes supported claims", () => {
  const issues = [
    { id: "i1", support_status: "unsupported" },
    { id: "i2", support_status: "partial" },
    { id: "i3", support_status: "supported" },
  ];
  // 1 accepted, 1 undecided, 1 supported (no choice needed)
  const choices = { i1: "accepted" };
  const result = computeAuthorChoices(issues, choices);

  assert.equal(result.totalCount, 3);
  assert.equal(result.reviewableCount, 2);
  assert.equal(result.acceptedCount, 1);
  assert.equal(result.keptCount, 0);
  assert.equal(result.undecidedCount, 1); // Not 2! Avoids mixing snapshot undecided with local choice
});

test("computeAuthorChoices with all supported claims reports 0 reviewable", () => {
  const issues = [
    { id: "i1", support_status: "supported" },
    { id: "i2", support_status: "supported" },
  ];
  const result = computeAuthorChoices(issues, {});
  assert.equal(result.totalCount, 2);
  assert.equal(result.reviewableCount, 0);
  assert.equal(result.undecidedCount, 0);
});

test("isImportedUnverified prioritizes latest review history over imported_from provenance", () => {
  const result = { mode: "preliminary", issues: [] };
  // Case 1: Re-checked locally, history[0].imported_unverified is false -> false
  const recheckedHistory = [{ imported_unverified: false, mode: "preliminary" }];
  assert.equal(isImportedUnverified(result, recheckedHistory, "external_pkg.json"), false);

  // Case 2: Newly imported unverified, history[0].imported_unverified is true -> true
  const unverifiedHistory = [{ imported_unverified: true, mode: "ai" }];
  assert.equal(isImportedUnverified(result, unverifiedHistory, "external_pkg.json"), true);

  // Case 3: Legacy imported package without history, has importedFrom -> true
  assert.equal(isImportedUnverified(result, [], "external_pkg.json"), true);

  // Case 4: Native project without importedFrom -> false
  assert.equal(isImportedUnverified(result, [], null), false);

  // Case 5: No review result -> false
  assert.equal(isImportedUnverified(null, recheckedHistory, "external_pkg.json"), false);
});

test("computeStatusBadge distinguishes editing, modified text, imported unverified, and dirty choices", () => {
  // 1. In-progress editor draft
  const editingBadge = computeStatusBadge({ editing: true, hasEdits: false, isDirty: false });
  assert.equal(editingBadge.statusTitle, "正文正在编辑 · 待复查");
  assert.equal(editingBadge.statusClass, "export-badge-warning");

  // 2. Saved or accepted text changes awaiting recheck
  const editsBadge = computeStatusBadge({ editing: false, hasEdits: true });
  assert.equal(editsBadge.statusTitle, "正文已修改 · 待复查");

  // 3. Imported unverified
  const importedBadge = computeStatusBadge({ editing: false, hasEdits: false, importedUnverified: true });
  assert.equal(importedBadge.statusTitle, "外部历史 · 未在本机复核");

  // 4. Author kept sentence or toggled choices without changing text
  const dirtyBadge = computeStatusBadge({ editing: false, hasEdits: false, isDirty: true });
  assert.equal(dirtyBadge.statusTitle, "作者取舍已变更 · 待保存");
  assert.match(dirtyBadge.statusDetail, /正文保持原句未改写/);

  // 5. Materials changed
  const materialBadge = computeStatusBadge({ editing: false, hasEdits: false, isDirty: false, needsReview: true });
  assert.equal(materialBadge.statusTitle, "材料已变化 · 待复查");

  // 6. Up-to-date review
  const cleanBadge = computeStatusBadge({
    editing: false,
    hasEdits: false,
    isDirty: false,
    needsReview: false,
    review: { label: "本地预检" },
  });
  assert.equal(cleanBadge.statusTitle, "最后检查：本地预检");
  assert.equal(cleanBadge.statusClass, "export-badge-current");
});

test("formatMaterialScope correctly formats saved, eligible, last used, and excluded count", () => {
  const materials = { total: 3, eligible_current: 1, unconfirmed_included: 1, excluded: 1 };
  const review = { last_used_material_count: 0 };
  const scopeStr = formatMaterialScope(materials, review);
  assert.equal(scopeStr, "已保存3份 · 授权准备纳入1份 · 上次纳入0份 · 排除1份");

  // Legacy unknown last_used_material_count
  const legacyReview = { last_used_material_count: null };
  const legacyScopeStr = formatMaterialScope(materials, legacyReview);
  assert.equal(legacyScopeStr, "已保存3份 · 授权准备纳入1份 · 上次纳入未知（旧记录未保存纳入范围） · 排除1份");

  // No excluded materials
  const cleanMaterials = { total: 2, eligible_current: 2, unconfirmed_included: 0, excluded: 0 };
  const cleanReview = { last_used_material_count: 2 };
  const cleanScopeStr = formatMaterialScope(cleanMaterials, cleanReview);
  assert.equal(cleanScopeStr, "已保存2份 · 授权准备纳入2份 · 上次纳入2份");
});

test("computeSummaryBanner accurately differentiates text changes from choice changes and font size changes", () => {
  // Case 1: Only choices changed (kept original sentence, text unchanged)
  const choicesOnlyBanner = computeSummaryBanner({
    editing: false,
    hasEdits: false,
    textChanged: false,
    choicesChanged: true,
    materialsChanged: false,
    version: 3,
  });
  assert.ok(choicesOnlyBanner);
  assert.equal(choicesOnlyBanner.isSnapshot, true);
  assert.match(choicesOnlyBanner.banner, /注意：作者取舍已变更 · 待保存/);
  assert.match(choicesOnlyBanner.banner, /当前正文保持原句未改写，本地取舍尚未保存/);
  // Must NOT claim that modified text is unreviewed!
  assert.doesNotMatch(choicesOnlyBanner.banner, /尚未基于当前修改后正文完成复查/);

  // Case 2: Text actually changed (adopted rewrite or editor draft)
  const textChangedBanner = computeSummaryBanner({
    editing: false,
    hasEdits: true,
    textChanged: true,
    choicesChanged: true,
    materialsChanged: false,
    version: 4,
  });
  assert.ok(textChangedBanner);
  assert.match(textChangedBanner.banner, /注意：当前导出正文存在未保存改动 · 待复查/);
  assert.match(textChangedBanner.banner, /尚未基于当前修改后正文完成复查/);

  // Case 3: Only font size changed (readingSize), no text/choices/materials changes
  const fontSizeOnlyBanner = computeSummaryBanner({
    editing: false,
    hasEdits: false,
    textChanged: false,
    choicesChanged: false,
    materialsChanged: false,
    version: 2,
  });
  assert.equal(fontSizeOnlyBanner, null);

  // Case 4: Materials changed
  const materialChangedBanner = computeSummaryBanner({
    editing: false,
    hasEdits: false,
    textChanged: false,
    choicesChanged: false,
    materialsChanged: true,
    version: 5,
  });
  assert.ok(materialChangedBanner);
  assert.match(materialChangedBanner.banner, /注意：项目材料已变更 · 待复查/);
});
