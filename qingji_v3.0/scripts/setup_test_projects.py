"""Helper script to populate test projects into isolated test database.
Ensures:
1. Exact string offsets for quotes and citations (asserted via Python).
2. Pure preliminary review preserves pending semantics.
3. Controlled AI fixture for supported/unsupported state and author choice tests.
4. Exact 1 saved, 0 eligible, 0 used material scope scenario.
5. Excluded unconfirmed material scenario.
6. Legacy result with None used_material_ids preserved as unknown.
7. Imported package with unverified history.
8. Unique IDs and names per run with manifest output.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.projects import ProjectStore
from core.project_packages import export_package, import_package
from core.review import Document, preliminary_review


def setup(db_path: str, run_id: str | None = None) -> dict[str, dict]:
    path = Path(db_path).resolve()
    qa_root = (ROOT / ".browser-test-output").resolve()
    # Guard: prevent accidental writes to production data/projects.sqlite3 or any location outside QA root
    normalized_str = str(path).replace("\\", "/")
    if "data/projects.sqlite3" in normalized_str or "qingji_v2.0/data" in normalized_str:
        raise ValueError("Cannot setup test projects in production database path.")
    try:
        path.relative_to(qa_root)
    except ValueError:
        raise ValueError(f"Target test database must reside within QA root directory '{qa_root}', got '{path}'.")
    if path.exists():
        raise FileExistsError(f"Target test database '{path}' already exists. Refusing to delete or overwrite existing test database.")
    path.parent.mkdir(parents=True, exist_ok=True)
    store = ProjectStore(path)

    run_id = run_id or time.strftime("%Y%m%d%H%M%S")
    manifest = {}

    # 1. Project 1: True Preliminary Review (pending semantics)
    text_prelim = "社区老旧供水管道在汛期经常停水。\n所有受访居民都表达了生活物资救助需求。"
    doc_report = Document("report", "社区调研报告", text_prelim)
    doc_mat_a = Document("m-eligible", "居民访谈记录A", "受访居民反映供水管道老化，下雨经常停水。")
    doc_mat_b = Document("m-unconfirmed", "居民访谈记录B", "另外一位居民表示生活正常。")
    doc_mat_c = Document("m-excluded", "团队背景文献", "参考背景文献资料。")
    
    prelim_res = preliminary_review(doc_report, [doc_mat_a, doc_mat_b, doc_mat_c])
    prelim_dict = prelim_res.to_dict()
    prelim_dict["used_material_ids"] = ["m-eligible"]

    p1 = store.create(
        f"虚构交付预检项目_{run_id}",
        {"name": "社区调研报告", "text": text_prelim},
        [
            {"id": "m-eligible", "name": "居民访谈记录A", "text": doc_mat_a.text, "source_role": "受访者陈述", "enabled": True, "consent_status": "confirmed"},
            {"id": "m-unconfirmed", "name": "居民访谈记录B", "text": doc_mat_b.text, "source_role": "受访者陈述", "enabled": True, "consent_status": "unconfirmed"},
            {"id": "m-excluded", "name": "团队背景文献", "text": doc_mat_c.text, "source_role": "团队分析", "enabled": False, "consent_status": "confirmed"},
        ]
    )
    p1 = store.reviewed(p1["id"], p1["version"], prelim_dict)
    manifest["preliminary"] = {"id": p1["id"], "name": p1["name"]}

    # 2. Project 2: Controlled AI Fixture (supported & unsupported with exact offsets)
    text_ctrl = "访谈对象反映供水经常出现中断。\n所有居民都需要生活物资帮助。"
    q1 = "访谈对象反映供水经常出现中断。"
    start1 = text_ctrl.index(q1)
    end1 = start1 + len(q1)
    assert text_ctrl[start1:end1] == q1, "Issue 1 quote offset mismatch"

    mat_ctrl_a_text = "访谈对象反映供水管道老化，经常停水。"
    cit_q1 = "经常停水"
    cit_start1 = mat_ctrl_a_text.index(cit_q1)
    cit_end1 = cit_start1 + len(cit_q1)
    assert mat_ctrl_a_text[cit_start1:cit_end1] == cit_q1, "Citation 1 offset mismatch"

    q2 = "所有居民都需要生活物资帮助。"
    start2 = text_ctrl.index(q2)
    end2 = start2 + len(q2)
    assert text_ctrl[start2:end2] == q2, "Issue 2 quote offset mismatch"

    mat_ctrl_b_text = "另外一位居民表示生活正常，无需物资帮助。"
    cit_q2 = "另外一位居民表示生活正常，无需物资帮助。"
    cit_start2 = mat_ctrl_b_text.index(cit_q2)
    cit_end2 = cit_start2 + len(cit_q2)
    assert mat_ctrl_b_text[cit_start2:cit_end2] == cit_q2, "Citation 2 offset mismatch"

    p2 = store.create(
        f"虚构受控核对项目_{run_id}",
        {"name": "受控社区调研报告", "text": text_ctrl},
        [
            {"id": "m-ctrl-a", "name": "居民访谈记录A", "text": mat_ctrl_a_text, "source_role": "受访者陈述", "enabled": True, "consent_status": "confirmed"},
            {"id": "m-ctrl-b", "name": "居民访谈记录B", "text": mat_ctrl_b_text, "source_role": "受访者陈述", "enabled": True, "consent_status": "confirmed"},
        ]
    )
    result_ctrl = {
        "mode": "ai",
        "report": {"name": "受控社区调研报告", "text": text_ctrl},
        "used_material_ids": ["m-ctrl-a", "m-ctrl-b"],
        "issues": [
            {
                "id": "iss-ctrl-sup",
                "start": start1,
                "end": end1,
                "quote": q1,
                "category": "其他",
                "support_status": "supported",
                "reason": "与居民反映供水管道老化经常停水记录相符。",
                "next_step": "保留该项结论。",
                "citations": [
                    {
                        "document_id": "m-ctrl-a",
                        "document_name": "居民访谈记录A",
                        "start": cit_start1,
                        "end": cit_end1,
                        "quote": cit_q1,
                        "relation": "support",
                    }
                ],
                "suggested_text": None,
            },
            {
                "id": "iss-ctrl-unsup",
                "start": start2,
                "end": end2,
                "quote": q2,
                "category": "范围外推",
                "support_status": "unsupported",
                "reason": "样本存在差异，另一位居民表示无需物资帮助。",
                "next_step": "核对受访对象覆盖范围并修正全称量词。",
                "citations": [
                    {
                        "document_id": "m-ctrl-b",
                        "document_name": "居民访谈记录B",
                        "start": cit_start2,
                        "end": cit_end2,
                        "quote": cit_q2,
                        "relation": "different",
                    }
                ],
                "suggested_text": "部分受访居民提出了生活改善需求。",
            },
        ],
        "notices": ["受控虚构核对历史记录，仅用于前端状态与取舍展示验证。"],
    }
    p2 = store.reviewed(p2["id"], p2["version"], result_ctrl)
    manifest["controlled"] = {"id": p2["id"], "name": p2["name"]}

    # 3. Project 3: Exact 1 saved, 0 eligible, 0 used scenario
    text_zero = "这是一份正文报告。"
    p3 = store.create(
        f"虚构未授权零纳入项目_{run_id}",
        {"name": "简报", "text": text_zero},
        [
            {"id": "m-unconf-only", "name": "未授权材料", "text": "材料内容", "source_role": "受访者陈述", "enabled": True, "consent_status": "unconfirmed"}
        ]
    )
    result_zero = {
        "mode": "preliminary",
        "report": {"name": "简报", "text": text_zero},
        "used_material_ids": [],
        "issues": [],
        "notices": ["未纳入任何未授权材料。"]
    }
    p3 = store.reviewed(p3["id"], p3["version"], result_zero)
    manifest["scope_zero"] = {"id": p3["id"], "name": p3["name"]}

    # 4. Project 4: Excluded Unconfirmed Material Scenario
    p4 = store.create(
        f"虚构排除未授权材料项目_{run_id}",
        {"name": "排查报告", "text": "排查报告正文。"},
        [
            {"id": "m-excl-unconf", "name": "未授权且主动排除材料", "text": "排除材料正文", "source_role": "受访者陈述", "enabled": False, "consent_status": "unconfirmed"},
            {"id": "m-excl-elig", "name": "已授权记录", "text": "已授权正文", "source_role": "正式记录", "enabled": True, "consent_status": "confirmed"}
        ]
    )
    result_excl = {
        "mode": "preliminary",
        "report": {"name": "排查报告", "text": "排查报告正文。"},
        "used_material_ids": ["m-excl-elig"],
        "issues": [],
        "notices": ["主动排除未授权材料。"]
    }
    p4 = store.reviewed(p4["id"], p4["version"], result_excl)
    manifest["scope_excluded"] = {"id": p4["id"], "name": p4["name"]}

    # 5. Project 5: Legacy project where used_material_ids is None
    p5 = store.create(
        f"虚构旧记录未知范围项目_{run_id}",
        {"name": "旧报告", "text": "旧社会实践报告正文。"},
        [{"id": "m-old", "name": "旧记录", "text": "旧记录正文。", "source_role": "正式记录", "enabled": True, "consent_status": "confirmed"}]
    )
    result_legacy = {
        "mode": "ai",
        "report": {"name": "旧报告", "text": "旧社会实践报告正文。"},
        "issues": [],
        "notices": ["旧检查记录，未保存纳入范围。"]
    }
    p5 = store.reviewed(p5["id"], p5["version"], result_legacy)
    with store.connect() as db:
        row = db.execute("SELECT data FROM projects WHERE id=?", (p5["id"],)).fetchone()
        data = json.loads(row[0])
        data["result"].pop("used_material_ids", None)
        db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), p5["id"]))
        db.commit()
    manifest["legacy"] = {"id": p5["id"], "name": p5["name"]}

    # 6. Project 6: Imported project with unverified history
    p6_src = store.create(
        f"虚构交接原始源项目_{run_id}",
        {"name": "交接报告", "text": "交接报告正文。"},
        [{"id": "m-imp", "name": "交接材料", "text": "材料正文。", "source_role": "受访者陈述", "enabled": True, "consent_status": "confirmed"}]
    )
    result_imp = {
        "mode": "preliminary",
        "report": {"name": "交接报告", "text": "交接报告正文。"},
        "used_material_ids": ["m-imp"],
        "issues": [],
        "notices": ["原始外部预检记录"]
    }
    p6_src = store.reviewed(p6_src["id"], p6_src["version"], result_imp)
    pkg = export_package(store, p6_src["id"])
    p6_imported = import_package(store, pkg, actor="交接测试员")
    with store.connect() as db:
        row = db.execute("SELECT data FROM projects WHERE id=?", (p6_imported["id"],)).fetchone()
        data = json.loads(row[0])
        data["name"] = f"虚构外部交接项目_{run_id}"
        db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), p6_imported["id"]))
        db.commit()
    manifest["imported"] = {"id": p6_imported["id"], "name": f"虚构外部交接项目_{run_id}"}

    # 7. Project 7: Controlled long report fixture with 6 issues of all support types
    q_l1 = "社区供水管道已完成全部改造。"
    q_l2 = "老年居民普遍需要智能手机一对一辅导。"
    q_l3 = "所有居民都强烈要求开设社区老年食堂。"
    q_l4 = "居民对加装电梯出资方案意见完全一致。"
    q_l5 = "青年志愿者每周固定参与社区巡逻两次。"
    q_l6 = "社区物业费收缴率达到百分之百。"
    report_text_long = f"{q_l1}{q_l2}{q_l3}{q_l4}{q_l5}{q_l6}"

    mat_la_text = "社区供水管道已完成全部改造。部分高龄独居居民反映需要智能手机辅导，大部分老人可自行使用微信。"
    mat_lb_text = "仅个别居民提出助餐设想，其他居民认为周围餐饮充足。高低楼层对加装电梯出资比例争议较大。物业费收缴总体平稳但存在因保修争议拒缴个案。"

    p7 = store.create(
        f"虚构长报告受控项目_{run_id}",
        {"name": "社区综合治理调研报告", "text": report_text_long},
        [
            {"id": "m-long-a", "name": "便民热线与管网台账", "text": mat_la_text, "source_role": "受访者陈述", "enabled": True, "consent_status": "confirmed"},
            {"id": "m-long-b", "name": "居民议事会记录", "text": mat_lb_text, "source_role": "现场观察", "enabled": True, "consent_status": "confirmed"},
        ],
        actor="测试管理员"
    )

    result_long = {
        "mode": "ai",
        "report": {"name": "社区综合治理调研报告", "text": report_text_long},
        "used_material_ids": ["m-long-a", "m-long-b"],
        "issues": [
            {
                "id": "iss-l1-sup",
                "start": report_text_long.index(q_l1),
                "end": report_text_long.index(q_l1) + len(q_l1),
                "quote": q_l1,
                "category": "其他",
                "support_status": "supported",
                "reason": "与台账记录及回访一致，供水改造已全面完成验收。",
                "next_step": "保留该项结论。",
                "citations": [{"document_id": "m-long-a", "document_name": "便民热线与管网台账", "start": mat_la_text.index(q_l1), "end": mat_la_text.index(q_l1) + len(q_l1), "quote": q_l1, "relation": "support"}],
                "suggested_text": None,
            },
            {
                "id": "iss-l2-part",
                "start": report_text_long.index(q_l2),
                "end": report_text_long.index(q_l2) + len(q_l2),
                "quote": q_l2,
                "category": "范围外推",
                "support_status": "partial",
                "reason": "材料表明仅高龄独居老人需要一对一辅导，不能概括为普遍需要。",
                "next_step": "细化受众范围并采纳限定改写。",
                "citations": [{"document_id": "m-long-a", "document_name": "便民热线与管网台账", "start": mat_la_text.index("部分高龄独居居民反映需要智能手机辅导"), "end": mat_la_text.index("部分高龄独居居民反映需要智能手机辅导") + len("部分高龄独居居民反映需要智能手机辅导，大部分老人可自行使用微信。"), "quote": "部分高龄独居居民反映需要智能手机辅导，大部分老人可自行使用微信。", "relation": "support"}],
                "suggested_text": "部分高龄独居老人反映需要智能手机辅导。",
            },
            {
                "id": "iss-l3-unsup",
                "start": report_text_long.index(q_l3),
                "end": report_text_long.index(q_l3) + len(q_l3),
                "quote": q_l3,
                "category": "缺乏依据",
                "support_status": "unsupported",
                "reason": "议事会记录显示仅个别居民提出，并未形成全社区普遍诉求。",
                "next_step": "客观表述建议来源或补充更大范围抽样数据。",
                "citations": [{"document_id": "m-long-b", "document_name": "居民议事会记录", "start": mat_lb_text.index("仅个别居民提出助餐设想"), "end": mat_lb_text.index("仅个别居民提出助餐设想") + len("仅个别居民提出助餐设想，其他居民认为周围餐饮充足。"), "quote": "仅个别居民提出助餐设想，其他居民认为周围餐饮充足。", "relation": "different"}],
                "suggested_text": "部分访谈对象建议改善社区助餐便利度。",
            },
            {
                "id": "iss-l4-disag",
                "start": report_text_long.index(q_l4),
                "end": report_text_long.index(q_l4) + len(q_l4),
                "quote": q_l4,
                "category": "存在矛盾",
                "support_status": "disagreement",
                "reason": "材料记录高低楼层对于出资分摊争议较大，结论断言意见完全一致与材料直接冲突。",
                "next_step": "如实呈现出资分歧与各方利益诉求。",
                "citations": [{"document_id": "m-long-b", "document_name": "居民议事会记录", "start": mat_lb_text.index("高低楼层对加装电梯出资比例争议较大。"), "end": mat_lb_text.index("高低楼层对加装电梯出资比例争议较大。") + len("高低楼层对加装电梯出资比例争议较大。"), "quote": "高低楼层对加装电梯出资比例争议较大。", "relation": "different"}],
                "suggested_text": "居民对加装电梯出资分摊方案存在不同看法。",
            },
            {
                "id": "iss-l5-pend",
                "start": report_text_long.index(q_l5),
                "end": report_text_long.index(q_l5) + len(q_l5),
                "quote": q_l5,
                "category": "待核对",
                "support_status": "pending",
                "reason": "材料中未见志愿者具体出勤频次记录，需核对志愿者台账。",
                "next_step": "核对出勤频次后确定是否保留固定次数表述。",
                "citations": [],
                "suggested_text": "志愿者按需参与社区巡逻（具体频次待核实）。",
            },
            {
                "id": "iss-l6-unsup2",
                "start": report_text_long.index(q_l6),
                "end": report_text_long.index(q_l6) + len(q_l6),
                "quote": q_l6,
                "category": "范围外推",
                "support_status": "unsupported",
                "reason": "材料记录存在因维保纠纷缓缴物业费情况，达不到百分之百。",
                "next_step": "核对实际缴费台账比例后修改结论。",
                "citations": [{"document_id": "m-long-b", "document_name": "居民议事会记录", "start": mat_lb_text.index("物业费收缴总体平稳但存在因保修争议拒缴个案。"), "end": mat_lb_text.index("物业费收缴总体平稳但存在因保修争议拒缴个案。") + len("物业费收缴总体平稳但存在因保修争议拒缴个案。"), "quote": "物业费收缴总体平稳但存在因保修争议拒缴个案。", "relation": "different"}],
                "suggested_text": "社区物业费收缴工作总体保持平稳。",
            }
        ],
        "notices": ["受控虚构核对历史记录，包含supported/partial/unsupported/disagreement/pending全部类型。"]
    }
    p7 = store.reviewed(p7["id"], p7["version"], result_long, actor="测试管理员")
    manifest["controlled_long"] = {"id": p7["id"], "name": p7["name"]}

    manifest_path = path.parent / "test-projects-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Test projects setup completed. Manifest written to {manifest_path}")
    return manifest


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else ".browser-test-output/export-status-rework-20261003/projects.sqlite3"
    rid = sys.argv[2] if len(sys.argv) > 2 else None
    setup(db, rid)
