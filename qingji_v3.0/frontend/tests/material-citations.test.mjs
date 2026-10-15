import assert from "node:assert/strict";
import test from "node:test";
import {
  getMaterialCitationsInfo,
  isMaterialSnapshotChanged,
  relationLabels
} from "../src/material-citations-helpers.js";

test("legacy unknown citation relationships never become support", () => {
  const material = {id:"m1"};
  const citations = [undefined, "", "unexpected", "support", "context"].map(relation => ({document_id:"m1",relation}));
  const info = getMaterialCitationsInfo({material,result:{issues:[{id:"i1",support_status:"unsupported",citations}]}});
  assert.deepEqual(info.citedIssues[0].relations,["unclassified","support","context"]);
  assert.deepEqual(info.citedIssues[0].relationLabels,["原文依据","支持记录","背景与限制"]);
  assert.equal(info.citedIssues[0].supportStatus,"unsupported");
});

test("getMaterialCitationsInfo - 无核对记录时返回 hasResult: false", () => {
  const m1 = { id: "m1", name: "材料一", text: "材料正文", enabled: true, consent_status: "confirmed" };
  const info = getMaterialCitationsInfo({ material: m1, result: null, reviewMaterials: [] });
  assert.equal(info.hasResult, false);
  assert.equal(info.citedCount, 0);
  assert.equal(info.citedIssues.length, 0);
});

test("getMaterialCitationsInfo - 纳入材料在上次核对中未被引用时返回 citedCount: 0", () => {
  const m1 = { id: "m1", name: "材料一", text: "材料正文", enabled: true, consent_status: "confirmed" };
  const result = {
    issues: [
      {
        id: "i1",
        quote: "结论一",
        support_status: "supported",
        citations: [{ document_id: "m2", document_name: "材料二", quote: "引文", relation: "support" }]
      }
    ]
  };
  const info = getMaterialCitationsInfo({ material: m1, result, reviewMaterials: [m1] });
  assert.equal(info.hasResult, true);
  assert.equal(info.citedCount, 0);
  assert.equal(info.citedIssues.length, 0);
});

test("getMaterialCitationsInfo - 同一材料被多条结论引用，去重并正确统计", () => {
  const m1 = { id: "m1", name: "访谈记录", text: "详细访谈记录文字", enabled: true, consent_status: "confirmed" };
  const result = {
    issues: [
      {
        id: "i1",
        quote: "结论一：社区设施基本完备",
        support_status: "partial",
        category: "设施情况",
        citations: [
          { document_id: "m1", document_name: "访谈记录", quote: "居委会主任表示已修缮健身器材", relation: "support" }
        ]
      },
      {
        id: "i2",
        quote: "结论二：居民普遍对绿化满意",
        support_status: "disagreement",
        category: "满意度",
        citations: [
          { document_id: "m1", document_name: "访谈记录", quote: "受访居民反映树木遮光影响采光", relation: "different" },
          { document_id: "m1", document_name: "访谈记录", quote: "部分居民提到修剪不够及时", relation: "context" }
        ]
      }
    ]
  };

  const info = getMaterialCitationsInfo({ material: m1, result, reviewMaterials: [m1] });
  assert.equal(info.hasResult, true);
  assert.equal(info.citedCount, 2);
  assert.equal(info.citedIssues.length, 2);

  // 结论一：1条引用，关系为 support
  const issue1 = info.citedIssues[0];
  assert.equal(issue1.issueId, "i1");
  assert.deepEqual(issue1.relations, ["support"]);
  assert.deepEqual(issue1.relationLabels, ["支持记录"]);
  assert.equal(issue1.citations.length, 1);

  // 结论二：同一材料同一 issue 多片段去重为一条结论，并保留 different 与 context 两种关系
  const issue2 = info.citedIssues[1];
  assert.equal(issue2.issueId, "i2");
  assert.deepEqual(issue2.relations, ["different", "context"]);
  assert.deepEqual(issue2.relationLabels, ["不同情况", "背景与限制"]);
  assert.equal(issue2.citations.length, 2);
});

test("getMaterialCitationsInfo - 严格排除 report 内部引文", () => {
  const m1 = { id: "m1", name: "材料一", text: "材料正文", enabled: true, consent_status: "confirmed" };
  const result = {
    issues: [
      {
        id: "i1",
        quote: "报告内原句引用",
        citations: [
          { document_id: "report", document_name: "报告正文", quote: "原文片段", relation: "support" }
        ]
      }
    ]
  };
  const info = getMaterialCitationsInfo({ material: m1, result, reviewMaterials: [m1] });
  assert.equal(info.citedCount, 0);
});

test("getMaterialCitationsInfo - 重复名称不同 ID 严格隔离", () => {
  const m1 = { id: "m1", name: "问卷数据", text: "问卷A", enabled: true, consent_status: "confirmed" };
  const m2 = { id: "m2", name: "问卷数据", text: "问卷B", enabled: true, consent_status: "confirmed" };
  const result = {
    issues: [
      {
        id: "i1",
        quote: "结论一",
        citations: [
          { document_id: "m2", document_name: "问卷数据", quote: "来自问卷B的片段", relation: "support" }
        ]
      }
    ]
  };

  const info1 = getMaterialCitationsInfo({ material: m1, result, reviewMaterials: [m1, m2] });
  assert.equal(info1.citedCount, 0, "m1 不应匹配 m2 的引用");

  const info2 = getMaterialCitationsInfo({ material: m2, result, reviewMaterials: [m1, m2] });
  assert.equal(info2.citedCount, 1, "m2 准确匹配");
});

test("isMaterialSnapshotChanged - 精确检测名称、文字、来源、授权与启用变更", () => {
  const base = {
    id: "m1",
    name: "访谈记录",
    text: "原始访谈文字",
    source_role: "受访者陈述",
    context: "社区广场",
    collected_at: "8月10日",
    consent_status: "confirmed",
    enabled: true
  };

  // 完全一致
  assert.equal(isMaterialSnapshotChanged(base, { ...base }), false);

  // 文字变更
  assert.equal(isMaterialSnapshotChanged({ ...base, text: "修改后的访谈文字" }, base), true);

  // 名称变更
  assert.equal(isMaterialSnapshotChanged({ ...base, name: "修改后的名称" }, base), true);

  // 来源类型变更
  assert.equal(isMaterialSnapshotChanged({ ...base, source_role: "工作人员说明" }, base), true);

  // 场景变更
  assert.equal(isMaterialSnapshotChanged({ ...base, context: "社区会议室" }, base), true);

  // 采集时间变更
  assert.equal(isMaterialSnapshotChanged({ ...base, collected_at: "8月12日" }, base), true);

  // 授权状态变更
  assert.equal(isMaterialSnapshotChanged({ ...base, consent_status: "unconfirmed" }, base), true);

  // 启用设置变更（排除）
  assert.equal(isMaterialSnapshotChanged({ ...base, enabled: false }, base), true);
});
