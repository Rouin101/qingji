import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  matchTaskIssue,
  analyzeEvidenceMaterials,
  getTaskResidentHint
} from "../src/evidence-feedback-helpers.js";

describe("evidence-feedback-helpers", () => {
  it("source-only changes remain snapshots and same-name unidentified citations are not guessed", () => {
    const old={id:"m1",name:"同名",text:"原文",source_role:"受访者陈述",context:"原场景",consent_status:"confirmed",enabled:true};
    const live={...old,source_role:"团队分析"};
    const issue={citations:[{document_name:"同名",quote:"原文",relation:"support"}]};
    const analysis=analyzeEvidenceMaterials({material_ids:["m1"]},issue,{materials:[live],review_materials:[old],result:{used_material_ids:["m1"]}});
    assert.equal(analysis.items[0].isModified,true);
    assert.equal(analysis.items[0].isCited,false);
    assert.equal(analysis.items[0].usedStatus,"included");
  });
  it("duplicate same-category tasks retain candidates without choosing the first", () => {
    const issues=[{id:"a",quote:"重复",category:"范围外推",start:0},{id:"b",quote:"重复",category:"范围外推",start:10}];
    const match=matchTaskIssue({kind:"evidence",quote:"重复",category:"范围外推"},{result:{issues}});
    assert.equal(match.status,"ambiguous");
    assert.equal(match.issue,null);
    assert.deepEqual(match.matches,issues);
    assert.equal(matchTaskIssue({kind:"evidence",quote:"重复",category:"范围外推"},{result:{issues:[{id:"c",quote:"重复"}]}}).status,"not_found");
  });
  describe("matchTaskIssue", () => {
    it("returns not_applicable for practice task", () => {
      const res = matchTaskIssue({ kind: "practice" }, { result: { issues: [] } });
      assert.equal(res.status, "not_applicable");
      assert.equal(res.issue, null);
    });

    it("returns not_found when project has no review issues", () => {
      const task = { kind: "evidence", quote: "句A" };
      const res = matchTaskIssue(task, { result: { issues: [] } });
      assert.equal(res.status, "not_found");
      assert.equal(res.issue, null);
    });

    it("returns unique when single issue matches quote", () => {
      const task = { kind: "evidence", quote: "句A", category: "c1" };
      const issue = { id: "i1", quote: "句A", category: "c1", support_status: "unsupported" };
      const res = matchTaskIssue(task, { result: { issues: [issue, { id: "i2", quote: "句B" }] } });
      assert.equal(res.status, "unique");
      assert.equal(res.issue.id, "i1");
      assert.equal(res.matchCount, 1);
    });

    it("returns not_found when quote has changed in new revision", () => {
      const task = { kind: "evidence", quote: "旧句A" };
      const res = matchTaskIssue(task, { result: { issues: [{ id: "i1", quote: "新句A" }] } });
      assert.equal(res.status, "not_found");
      assert.equal(res.issue, null);
    });

    it("returns ambiguous when multiple issues share same quote", () => {
      const task = { kind: "evidence", quote: "重复句" };
      const res = matchTaskIssue(task, {
        result: {
          issues: [
            { id: "i1", quote: "重复句", category: "c1" },
            { id: "i2", quote: "重复句", category: "c1" }
          ]
        }
      });
      assert.equal(res.status, "ambiguous");
      assert.equal(res.issue, null);
      assert.equal(res.matchCount, 2);
    });
  });

  describe("analyzeEvidenceMaterials", () => {
    it("analyzes included and cited materials correctly", () => {
      const task = {
        kind: "evidence",
        material_ids: ["m1", "m2"]
      };
      const matchedIssue = {
        id: "i1",
        citations: [
          { document_id: "m1", quote: "引用片段1", relation: "support" },
          { document_id: "m1", quote: "引用片段2", relation: "different" }
        ]
      };
      const project = {
        materials: [
          { id: "m1", name: "材料一", text: "正文1", enabled: true, consent_status: "confirmed" },
          { id: "m2", name: "材料二", text: "正文2", enabled: true, consent_status: "confirmed" }
        ],
        review_materials: [
          { id: "m1", name: "材料一", text: "正文1" },
          { id: "m2", name: "材料二", text: "正文2" }
        ],
        result: {
          used_material_ids: ["m1", "m2"]
        }
      };

      const analysis = analyzeEvidenceMaterials(task, matchedIssue, project);
      assert.equal(analysis.totalAssociated, 2);
      assert.equal(analysis.includedCount, 2);
      assert.equal(analysis.citedCount, 1);
      assert.equal(analysis.isScopeUnknown, false);

      const item1 = analysis.items.find(i => i.id === "m1");
      assert.equal(item1.usedStatus, "included");
      assert.equal(item1.isCited, true);
      assert.equal(item1.citations.length, 2);
      assert.equal(item1.citations[0].relationLabel, "支持记录");
      assert.equal(item1.citations[1].relationLabel, "不同情况与观点");

      const item2 = analysis.items.find(i => i.id === "m2");
      assert.equal(item2.usedStatus, "included");
      assert.equal(item2.isCited, false);
      assert.equal(item2.citations.length, 0);
    });

    it("handles unknown scope when used_material_ids is null", () => {
      const task = { material_ids: ["m1"] };
      const project = {
        materials: [{ id: "m1", name: "材料一", text: "正文", enabled: true, consent_status: "confirmed" }],
        result: { used_material_ids: null }
      };
      const analysis = analyzeEvidenceMaterials(task, null, project);
      assert.equal(analysis.isScopeUnknown, true);
      assert.equal(analysis.includedCount, null);
      assert.equal(analysis.items[0].usedStatus, "unknown");
    });

    it("detects removed and modified materials via review_materials snapshot", () => {
      const task = { material_ids: ["m-removed", "m-modified"] };
      const project = {
        materials: [
          { id: "m-modified", name: "材料改名", text: "新内容", enabled: false, consent_status: "unconfirmed" }
        ],
        review_materials: [
          { id: "m-removed", name: "已删材料", text: "旧内容" },
          { id: "m-modified", name: "旧材料名", text: "旧内容" }
        ],
        result: {
          used_material_ids: ["m-removed", "m-modified"]
        }
      };
      const analysis = analyzeEvidenceMaterials(task, null, project);
      const itemRemoved = analysis.items.find(i => i.id === "m-removed");
      assert.equal(itemRemoved.isRemoved, true);
      assert.equal(itemRemoved.name, "已删材料");

      const itemModified = analysis.items.find(i => i.id === "m-modified");
      assert.equal(itemModified.isModified, true);
      assert.equal(itemModified.isExcluded, true);
      assert.equal(itemModified.isConsentRevoked, true);
    });
  });

  describe("getTaskResidentHint", () => {
    it("returns empty string for practice task", () => {
      assert.equal(getTaskResidentHint({ kind: "practice" }), "");
    });

    it("returns recheck prompt when last_review_at is missing", () => {
      assert.equal(
        getTaskResidentHint({ kind: "evidence", last_review_at: null }),
        "补充材料并复查后，可在此查看核对反馈"
      );
    });

    it("returns not_found hint when sentence changed", () => {
      const task = { kind: "evidence", last_review_at: "2026-10-04T00:00:00Z" };
      assert.equal(
        getTaskResidentHint(task, null, "not_found"),
        "原句在新版本中已变化，无法对应当前结论"
      );
    });

    it("returns unique hint with support status", () => {
      const task = {
        kind: "evidence",
        last_review_at: "2026-10-04T00:00:00Z",
        material_ids: ["m1", "m2"]
      };
      const issue = { support_status: "unsupported" };
      assert.equal(
        getTaskResidentHint(task, issue, "unique"),
        "上次核对判断：依据不足 · 关联 2 份材料"
      );
    });
  });
});
