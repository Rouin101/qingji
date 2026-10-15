"""整理已保存项目的交付前状态；不审核事实、不修改项目、不授予通过状态。"""
from __future__ import annotations

from datetime import datetime, timezone
from core.collaboration import pending_author_edits

SUPPORT_LABELS = {"supported":"有对应依据", "partial":"支持较窄表述", "unsupported":"依据不足",
                  "disagreement":"存在不同情况", "pending":"待结合依据核对"}
MODES = {"ai":"AI审阅", "preliminary":"本地预检", "example":"虚构示例", "none":"尚未核对"}
TASK_LABELS = {"open":"待补充", "material_added":"已添材料，待复查",
               "awaiting_confirmation":"已复查，待确认", "done":"作者确认完成"}


def delivery_check(project):
    result = project.get("result") or {}
    issues = result.get("issues", [])
    mode = result.get("mode", "none")
    materials = project.get("materials", [])
    eligible = [m for m in materials if m.get("enabled") is True and m.get("consent_status") == "confirmed"]
    pending = [m for m in materials if m.get("enabled") is True and m.get("consent_status") != "confirmed"]
    excluded = [m for m in materials if m.get("enabled") is not True]
    edits = pending_author_edits(project)
    history = project.get("history") or []
    imported_unverified = bool(result) and bool(history[0].get("imported_unverified") if history else project.get("imported_from"))
    current = bool(result) and not project.get("needs_review") and not edits and not imported_unverified
    used_ids = result.get("used_material_ids")
    used = len(set(used_ids)) if isinstance(used_ids, list) else None
    choices = project.get("choices", {})
    undecided = [i for i in issues if i.get("support_status", "pending") != "supported"
                 and choices.get(i["id"]) not in {"kept", "accepted"}]
    open_tasks = [t for t in project.get("tasks", []) if t.get("status") != "done"]
    material_ids = {m["id"] for m in materials}
    links = [{"task_id":t["id"], "action":t["action"],
              "missing_ids":[mid for mid in t.get("material_ids", []) if mid not in material_ids]}
             for t in project.get("tasks", []) if t.get("kind") == "evidence"
             and any(mid not in material_ids for mid in t.get("material_ids", []))]
    review_items = []
    if not (project.get("report") or {}).get("text", "").strip():
        review_items.append({"label":"还没有报告正文", "target":"project"})
    if not result:
        review_items.append({"label":"尚未核对当前报告", "target":"project"})
    elif project.get("needs_review") or edits:
        review_items.append({"label":"正文或材料有待复查的变化", "target":"project"})
    if mode in {"preliminary", "example"}:
        review_items.append({"label":"当前记录是本地预检" if mode == "preliminary" else "当前记录是虚构示例",
                             "detail":"尚未形成真实AI对当前材料的判断。", "target":"project"})
    if imported_unverified:
        review_items.append({"label":"外部历史，未在本机复核", "detail":"交接文件中的判断仍保留，需要在本机确认材料授权并复查。", "target":"project"})
    sections = [
        {"id":"review", "title":"核对范围", "target":"project", "items":review_items},
        {"id":"materials", "title":"未纳入的材料", "target":"materials", "items":[
            {"material_id":m["id"], "label":m["name"], "detail":"已保存、准备纳入，但尚未确认引用与处理授权。"}
            for m in pending]},
        {"id":"choices", "title":"尚未处理的结论", "target":"review", "items":[
            {"issue_id":i["id"], "label":i["quote"], "detail":SUPPORT_LABELS.get(i.get("support_status", "pending"), "待结合依据核对")}
            for i in undecided]},
        {"id":"tasks", "title":"未完成的行动", "target":"project", "items":[
            {"task_id":t["id"], "label":t["action"], "detail":("实践行动" if t.get("kind") == "practice" else "补证")
             + " · " + TASK_LABELS.get(t.get("status"), "待确认")}
            for t in open_tasks]},
        {"id":"links", "title":"需要更新的材料关联", "target":"project", "items":[
            {"task_id":l["task_id"], "label":l["action"], "detail":f"{len(l['missing_ids'])}份旧材料已移除，请明确选择当前材料。"}
            for l in links]},
    ]
    support_counts = {status:sum(i.get("support_status", "pending") == status for i in issues) for status in SUPPORT_LABELS}
    return {"project_id":project["id"], "project_name":project["name"], "version":project["version"],
            "checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notice":"这是交付前状态整理，不判定报告通过，也不证明材料真实。",
            "review":{"mode":mode, "label":"外部历史 · 未在本机复核" if imported_unverified else MODES.get(mode, "未知检查方式"), "current":current,
                      "imported_unverified":imported_unverified,
                      "pending_author_edits":edits, "last_used_material_count":used,
                      "last_review_at":history[0].get("created_at") if history else None,
                      "support_counts":support_counts},
            "materials":{"total":len(materials), "eligible_current":len(eligible),
                         "unconfirmed_included":len(pending), "excluded":len(excluded)},
            "counts":{"undecided_claims":len(undecided), "open_practice_tasks":sum(t.get("kind") == "practice" for t in open_tasks),
                      "open_evidence_tasks":sum(t.get("kind") == "evidence" for t in open_tasks),
                      "missing_material_links":len(links), "attention_items":sum(len(s["items"]) for s in sections)},
            "sections":sections}


def delivery_markdown(check):
    review, mats = check["review"], check["materials"]
    scope = "未知（旧记录未保存纳入范围）" if review["last_used_material_count"] is None else str(review["last_used_material_count"])+"份"
    rows = [f"# {check['project_name']} · 交付前检查", check["notice"],
            f"项目版本：{check['version']}\n\n检查状态整理时间：{check['checked_at']}",
            f"最后检查：{review['label']}；{'对应当前保存内容' if review['current'] else '尚未核对或需要复查'}。",
            f"最后核对纳入材料：{scope}。当前已保存{mats['total']}份，已授权准备纳入{mats['eligible_current']}份，"
            f"准备纳入但未授权{mats['unconfirmed_included']}份，明确排除{mats['excluded']}份。",
            "## 已保存判断的支持状态", "；".join(f"{SUPPORT_LABELS[s]}：{n}" for s,n in review['support_counts'].items()),
            "作者选择与支持程度分开记录；保留原句或完成任务不会把依据不足改成有依据。"]
    if not review["current"]:
        rows.append("以下判断与作者选择属于已保存记录，不能代替对最新正文和材料的复查。")
    for section in check["sections"]:
        rows.append("## "+section["title"])
        rows.extend(f"- {item['label']}"+(f"\n  {item['detail']}" if item.get('detail') else "") for item in section["items"])
        if not section["items"]:
            rows.append("当前没有此类待处理项；不据此认定报告通过。")
    rows.append("明确排除的材料不要求补授权；实际是否充分覆盖结论仍需结合原文与依据核对。")
    return "\n\n".join(rows)+"\n"
