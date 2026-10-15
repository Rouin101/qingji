"""独立本地项目库：原文、来源语境、补证与审阅版本。"""
from __future__ import annotations
import copy
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from core.review import ReviewError, MAX_REPORT_CHARS, MAX_MATERIAL_CHARS
from core.review_changes import review_changes
from core.collaboration import (MAX_COMMENTS, MAX_TASKS, assignee, declared_actor, due_date,
                                material_tags, members_list, migrate, overdue_count, pending_author_edits,
                                record_activity, reopen_completed_evidence,
                                result_fingerprint,
                                short_text, target_snapshot, with_comment_states)

ROLES = {"待确认", "受访者陈述", "工作人员说明", "现场观察", "正式记录", "团队分析"}

class ProjectConflict(ReviewError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def text(value, label, limit, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ReviewError(f"{label}不完整或过长。")
    return value

def document(item, material=False):
    if not isinstance(item, dict):
        raise ReviewError("材料内容不完整。")
    role = item.get("source_role", "待确认")
    if not isinstance(role, str) or role not in ROLES:
        raise ReviewError("请选择有效的来源类型。")
    notes = item.get("notes", [])
    if not isinstance(notes, (tuple, list)) or any(not isinstance(n, str) or len(n)>1000 for n in notes):
        raise ReviewError("材料读取说明不完整。")
    value = {"id": item.get("id", ""), "name": text(item.get("name", "未命名材料"), "名称", 200, False),
             "text": text(item.get("text", ""), "正文", MAX_MATERIAL_CHARS if material else MAX_REPORT_CHARS),
             "notes": list(notes), "source_role": role,
             "context": text(item.get("context", ""), "采集场景", 1000),
             "collected_at": text(item.get("collected_at", ""), "采集时间", 100)}
    if material:
        value.update(enabled=item.get("enabled", True), consent_status=item.get("consent_status", "unconfirmed"),
                     tags=material_tags(item.get("tags",[])))
        if type(value["enabled"]) is not bool or not isinstance(value["consent_status"],str) or value["consent_status"] not in {"confirmed", "unconfirmed"}:
            raise ReviewError("材料的引用或处理授权状态不完整。")
    else:
        value["id"] = "report"
    return value

def material_list(items):
    if not isinstance(items, list) or len(items)>8:
        raise ReviewError("每个项目目前最多保存八份补充材料。")
    result=[]
    for item in items:
        d=document(item, True)
        if not d["text"].strip():
            raise ReviewError("补充材料不能为空。")
        if not isinstance(d["id"], str) or not d["id"].startswith("m") or len(d["id"])>80:
            d["id"]="m"+uuid.uuid4().hex
        result.append(d)
    if len({d["id"] for d in result}) != len(result):
        raise ReviewError("材料标识不能重复。")
    if sum(len(d["text"]) for d in result)>MAX_MATERIAL_CHARS:
        raise ReviewError("项目材料总文字超过48,000字，请精简或分开项目。")
    return result

class ProjectStore:
    def __init__(self, path: Path):
        self.path=Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db=sqlite3.connect(self.path, timeout=20)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), created_at TEXT NOT NULL, data TEXT NOT NULL)")
        db.commit()
        return db

    def review_materials(self, db, project):
        """引用跟随审阅时的材料，不能被后来编辑的正文或授权替代。"""
        if not project.get("result"):
            return []
        if "review_materials" in project:
            return copy.deepcopy(project["review_materials"])
        fingerprint=result_fingerprint(project["result"])
        for row in db.execute("SELECT data FROM revisions WHERE project_id=? ORDER BY rowid DESC",(project["id"],)):
            entry=json.loads(row[0])
            if result_fingerprint(entry.get("result"))==fingerprint:
                return copy.deepcopy(entry.get("materials",[]))
        return []

    def get(self, project_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            row=db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise ReviewError("找不到这个实践项目。")
            value=migrate(json.loads(row[0]))
            value["review_materials"]=self.review_materials(db,value)
            revisions=db.execute("SELECT id,created_at,data FROM revisions WHERE project_id=? ORDER BY rowid DESC LIMIT 100", (project_id,)).fetchall()
            value["history"]=[]
            for r in revisions:
                entry=json.loads(r[2])
                value["history"].append({"id":r[0],"created_at":r[1],"mode":entry["result"]["mode"],
                    "count":len(entry["result"]["issues"]),"summary":entry["summary"],
                    "imported_unverified":bool(entry.get("imported_unverified"))})
            return with_comment_states(value)

    def list(self):
        with closing(self.connect()) as db, db:
            values=[migrate(json.loads(row[0])) for row in db.execute("SELECT data FROM projects ORDER BY rowid DESC")]
            latest_unverified = {}
            for r in db.execute("SELECT project_id, data FROM revisions ORDER BY rowid DESC"):
                pid = r[0]
                if pid not in latest_unverified:
                    try:
                        latest_unverified[pid] = bool(json.loads(r[1]).get("imported_unverified"))
                    except Exception:
                        latest_unverified[pid] = False
        values.sort(key=lambda p:p["updated_at"],reverse=True)
        return [{k:p[k] for k in ("id","name","description","updated_at","version")} | {
            "material_count":len(p["materials"]), "claim_count":len((p["result"] or {}).get("issues",[])),
            "task_count":sum(t["status"]!="done" for t in p["tasks"]),"mode":(p["result"] or {}).get("mode"),
            "is_example":p["is_example"],"archived":p["archived"],"team_count":len(p["members"]),
            "overdue_count":overdue_count(p),
            "has_result":bool(p.get("result")),
            "needs_review":bool(p.get("needs_review") or pending_author_edits(p)),
            "imported_unverified":latest_unverified.get(p["id"], bool(p.get("imported_from")))} for p in values]

    def create(self, name, report=None, materials=None, result=None, is_example=False, actor=""):
        p={"id":uuid.uuid4().hex, "name":text(name,"项目名称",200,False), "description":"", "version":1,
           "created_at":now(),"updated_at":now(),"report":document(report or {"name":"社会实践报告","text":""}),
           "materials":material_list(materials or []),"result":result,"choices":{},"manual_text":None,
           "reading_size":16,"tasks":[],"needs_review":False,"is_example":is_example,
           "members":[],"comments":[],"activity":[],"activity_earlier_count":0,
           "archived":False,"archived_at":None}
        record_activity(p,"created",actor,p["created_at"],"创建实践项目")
        p["review_materials"]=copy.deepcopy(p["materials"]) if result else []
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO projects VALUES (?,?)",(p["id"],json.dumps(p,ensure_ascii=False)))
        return self.get(p["id"])

    def update(self, project_id, version, mutate, revision=False, actor="", action="updated", detail="更新项目"):
        declared_actor(actor)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT data FROM projects WHERE id=?",(project_id,)).fetchone()
            if not row:
                raise ReviewError("找不到这个实践项目。")
            p=migrate(json.loads(row[0]))
            p["review_materials"]=self.review_materials(db,p)
            if type(version) is not int or version!=p["version"]:
                raise ProjectConflict("项目已在另一个操作中更新，请重新打开项目后再保存。")
            old=copy.deepcopy(p)
            mutate(p)
            if p==old and not revision:
                db.commit()
                return self.get(project_id)
            p["version"]+=1
            p["updated_at"]=now()
            record_activity(p,action,actor,p["updated_at"],detail)
            if revision:
                entry={"result":p["result"],"materials":copy.deepcopy(p["materials"]),
                       "choices":old["choices"],"previous_report":old["report"],
                       "previous_result":old["result"],"previous_manual_text":old["manual_text"],
                       "previous_materials":copy.deepcopy(old["review_materials"]),
                       "summary":f"整篇复查 · {len(p['materials'])}份项目材料 · {len(p['result']['issues'])}条核对记录"}
                db.execute("INSERT INTO revisions VALUES (?,?,?,?)",(uuid.uuid4().hex,p["id"],now(),json.dumps(entry,ensure_ascii=False)))
            db.execute("UPDATE projects SET data=? WHERE id=?",(json.dumps(p,ensure_ascii=False),p["id"]))
        return self.get(project_id)

    def save(self, project_id, version, changes, actor=""):
        if not isinstance(changes,dict):
            raise ReviewError("项目修改内容不完整。")
        def mutate(p):
            for key, limit in (("name",200),("description",2000)):
                if key in changes:
                    p[key]=text(changes[key],"项目名称" if key=="name" else "项目简介",limit,key!="name")
            if "report" in changes:
                report=document(changes["report"])
                if report!=p["report"]:
                    reopen_completed_evidence(p,actor,now(),"报告正文或来源已变化")
                    p["report"]=report
                    p["result"]=None
                    p["review_materials"]=[]
                    p["choices"]={}
                    p["manual_text"]=None
                    p["needs_review"]=True
            if "materials" in changes:
                mats=material_list(changes["materials"])
                if mats!=p["materials"]:
                    previous_scope=[{k:v for k,v in m.items() if k!="tags"} for m in p["materials"]]
                    next_scope=[{k:v for k,v in m.items() if k!="tags"} for m in mats]
                    p["materials"]=mats
                    if previous_scope!=next_scope:
                        p["needs_review"]=True
                        reopen_completed_evidence(p,actor,now(),"材料或处理授权范围已变化")
            if "choices" in changes:
                choices=changes["choices"]
                ids={i["id"] for i in (p["result"] or {}).get("issues",[])}
                if not isinstance(choices,dict) or any(k not in ids or not isinstance(v,str) or v not in {"accepted","kept"} for k,v in choices.items()):
                    raise ReviewError("结论取舍无法对应当前检查记录。")
                p["choices"]=choices
            if "manual_text" in changes:
                p["manual_text"]=None if changes["manual_text"] is None else text(changes["manual_text"],"编辑正文",MAX_REPORT_CHARS)
            if "reading_size" in changes:
                if type(changes["reading_size"]) is not int or changes["reading_size"] not in (16,18,20,22):
                    raise ReviewError("字号无效。")
                p["reading_size"]=changes["reading_size"]
            if pending_author_edits(p):
                reopen_completed_evidence(p,actor,now(),"作者正文已有待复查编辑")
        return self.update(project_id,version,mutate,actor=actor,action="saved",detail="保存项目资料或作者取舍")

    def reviewed(self, project_id, version, result, actor=""):
        def mutate(p):
            if result_fingerprint(result)!=result_fingerprint(p["result"]):
                reopen_completed_evidence(p,actor,now(),"核验判断已更新")
            p.update(result=result,report=result["report"],choices={},manual_text=None,needs_review=False)
            p["review_materials"]=copy.deepcopy(p["materials"])
            for task in p["tasks"]:
                if task["kind"]=="evidence" and task["status"]!="done":
                    task["status"]="awaiting_confirmation"
                    task["last_review_at"]=now()
        return self.update(project_id,version,mutate,True,actor=actor,action="reviewed",detail="完成整篇结论复查")

    def supplement(self, project_id, version, issue_id, added, actor=""):
        def mutate(p):
            issue=next((i for i in (p["result"] or {}).get("issues",[]) if i["id"]==issue_id),None)
            if not issue:
                raise ReviewError("这条结论已变化，请先查看最新记录。")
            mats=material_list(p["materials"]+[added]) if added else p["materials"]
            if added:
                reopen_completed_evidence(p,actor,now(),"新增补证材料，核验范围已变化")
            task=next((t for t in p["tasks"] if t["quote"]==issue["quote"] and t["category"]==issue["category"]),None)
            if not task:
                if len(p["tasks"])>=MAX_TASKS:
                    raise ReviewError(f"每个项目目前最多记录 {MAX_TASKS} 项任务。")
                task={"id":uuid.uuid4().hex,"quote":issue["quote"],"category":issue["category"],
                      "action":issue["next_step"],"created_at":now(),"material_ids":[],"status":"open",
                      "kind":"evidence","assignee_id":"","due_date":"","notes":""}
                p["tasks"].append(task)
            if added:
                task["material_ids"].append(mats[-1]["id"])
                task["status"]="material_added"
                p["materials"]=mats
                p["needs_review"]=True
            else:
                task["status"]="open"
        return self.update(project_id,version,mutate,actor=actor,action="supplemented",
                           detail="上传补证材料" if added else "记录补证任务")

    def task(self, project_id, version, task_id, status, actor=""):
        if not isinstance(status,str) or status not in {"open","done"}:
            raise ReviewError("任务状态无效。")
        def mutate(p):
            t=next((t for t in p["tasks"] if t["id"]==task_id),None)
            if not t:
                raise ReviewError("找不到这项补证任务。")
            if t["kind"]=="evidence" and status=="done" and (p["needs_review"] or pending_author_edits(p) or not t.get("last_review_at")):
                raise ReviewError("请先用当前材料复查，再确认补证完成。")
            eligible={m["id"] for m in p["materials"] if m["enabled"] and m["consent_status"]=="confirmed"}
            if t["kind"]=="evidence" and status=="done" and any(mid not in eligible for mid in t["material_ids"]):
                raise ReviewError("关联的补充材料尚未授权或已排除，请处理后复查再确认。")
            if t["status"]==status:
                return
            t["status"]=status
            if status=="done":
                t["confirmed_at"]=now()
        return self.update(project_id,version,mutate,actor=actor,action="task_status",
                           detail="确认任务完成" if status=="done" else "重新打开任务")

    def members(self, project_id, version, members, actor=""):
        roster=members_list(members)
        def mutate(p):
            removed={m["id"] for m in p["members"]}-{m["id"] for m in roster}
            unassigned=0
            for task in p["tasks"]:
                if task["assignee_id"] in removed:
                    task["assignee_id"]=""
                    unassigned+=1
            p["members"]=roster
            if unassigned:
                record_activity(p,"task_unassigned",actor,now(),f"成员移除，解除 {unassigned} 项任务的负责人")
        return self.update(project_id,version,mutate,actor=actor,action="members",detail="更新成员与实践分工")

    def task_detail(self, project_id, version, task_id, changes, actor=""):
        if not isinstance(changes,dict) or any(k not in {"action","assignee_id","due_date","notes","material_ids"} for k in changes):
            raise ReviewError("任务修改内容无效。")
        def mutate(p):
            task=next((t for t in p["tasks"] if t["id"]==task_id),None)
            if not task:
                raise ReviewError("找不到这个项目中的任务。")
            if "action" in changes:
                task["action"]=short_text(changes["action"],"任务内容",1000,True)
            if "assignee_id" in changes:
                task["assignee_id"]=assignee(p,changes["assignee_id"])
            if "due_date" in changes:
                task["due_date"]=due_date(changes["due_date"])
            if "notes" in changes:
                task["notes"]=short_text(changes["notes"],"任务记录",3000)
            if "material_ids" in changes:
                mids=changes["material_ids"]
                current={m["id"]:m for m in p["materials"]}
                if task["kind"]!="evidence":
                    raise ReviewError("独立实践分工不能设置补证材料关联。")
                if (not isinstance(mids,list) or len(mids)>8
                        or any(not isinstance(mid,str) or mid not in current for mid in mids)
                        or len(set(mids))!=len(mids)):
                    raise ReviewError("请从当前项目选择不重复的关联材料，最多八份。")
                if set(mids)!=set(task["material_ids"]):
                    snapshots={m["id"]:m for m in p.get("review_materials",[])} | current
                    def describe(ids):
                        return "、".join(f"{mid}（{snapshots.get(mid,{}).get('name','已移除材料')[:60]}）" for mid in ids) or "无"
                    before=describe(task["material_ids"])
                    task["material_ids"]=list(mids)
                    task["status"]="open"
                    p["needs_review"]=True
                    # 原材料与旧引文仍在版本快照中；仅作者显式提交才能替换当前任务关联。
                    record_activity(p,"task_materials",actor,now(),
                                    f"调整补证材料：{before} → {describe(mids)}；待整篇复查和作者确认。")
        return self.update(project_id,version,mutate,actor=actor,action="task_detail",detail="更新任务分工、日期或记录")

    def create_task(self, project_id, version, action, assignee_id="", due_date="", notes="", actor=""):
        from core.collaboration import due_date as validate_due_date
        def mutate(p):
            if len(p["tasks"])>=MAX_TASKS:
                raise ReviewError(f"每个项目目前最多记录 {MAX_TASKS} 项任务。")
            p["tasks"].append({"id":uuid.uuid4().hex,"kind":"practice","action":short_text(action,"任务内容",1000,True),
                               "assignee_id":assignee(p,assignee_id),"due_date":validate_due_date(due_date),
                               "notes":short_text(notes,"任务记录",3000),"status":"open","created_at":now(),
                               "quote":"","category":"实践任务","material_ids":[]})
        return self.update(project_id,version,mutate,actor=actor,action="task_created",detail="新建实践任务")

    def comment(self, project_id, version, target_type, target_id, body, actor=""):
        target_type=short_text(target_type,"讨论对象",20,True)
        body=short_text(body,"讨论内容",3000,True)
        author=declared_actor(actor)
        def mutate(p):
            if len(p["comments"])>=MAX_COMMENTS:
                raise ReviewError(f"项目已保存 {MAX_COMMENTS} 条讨论，请在新项目中继续记录。")
            normalized_id,snapshot=target_snapshot(p,target_type,target_id)
            p["comments"].append({"id":uuid.uuid4().hex,"target_type":target_type,"target_id":normalized_id,
                                  "target_snapshot":snapshot,"body":body,"actor":author,"created_at":now()})
        return self.update(project_id,version,mutate,actor=actor,action="commented",detail="补充项目讨论")

    def archive(self, project_id, version, archived, actor=""):
        if type(archived) is not bool:
            raise ReviewError("归档状态无效。")
        def mutate(p):
            if p["archived"]!=archived:
                p["archived"]=archived
                p["archived_at"]=now() if archived else None
        return self.update(project_id,version,mutate,actor=actor,action="archived" if archived else "restored",
                           detail="归档实践项目" if archived else "恢复实践项目")

    def revision(self, project_id, revision_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            row=db.execute("SELECT rowid,data FROM revisions WHERE project_id=? AND id=?",(project_id,revision_id)).fetchone()
            if not row:
                raise ReviewError("找不到这次项目检查记录。")
            entry=json.loads(row[1])
            stored_project=db.execute("SELECT data FROM projects WHERE id=?",(project_id,)).fetchone()
            project=json.loads(stored_project[0])
            previous_fingerprint=result_fingerprint(entry.get("previous_result"))
            previous_entry=None
            if previous_fingerprint:
                for previous in db.execute("SELECT data FROM revisions WHERE project_id=? AND rowid<? ORDER BY rowid DESC",(project_id,row[0])):
                    candidate=json.loads(previous[0])
                    if result_fingerprint(candidate.get("result"))==previous_fingerprint:
                        previous_entry=candidate
                        break
            previous_materials_known="previous_materials" in entry or previous_entry is not None
            if "previous_materials" not in entry:
                entry["previous_materials"]=copy.deepcopy(previous_entry.get("materials",[])) if previous_entry else []
            # 讨论保存在项目中，本次读取按完整判断指纹恢复归属；不改历史JSON或项目包指纹。
            entry["discussions"]={"current_review":[],"previous_review":[]}
            previous_unverified=(bool(previous_entry.get("imported_unverified")) if previous_entry
                                 else bool(entry.get("imported_unverified") or project.get("imported_from")))
            for group,result,unverified in (("current_review",entry.get("result"),bool(entry.get("imported_unverified"))),
                                             ("previous_review",entry.get("previous_result"),previous_unverified)):
                if not result:
                    continue
                fingerprint=result_fingerprint(result)
                issues={i["id"]:i for i in result.get("issues",[])}
                for comment in project.get("comments",[]):
                    if comment.get("target_type")!="issue":
                        continue
                    snapshot=comment.get("target_snapshot")
                    issue=issues.get(comment.get("target_id"))
                    if (not isinstance(snapshot,dict) or not issue or snapshot.get("result_fingerprint")!=fingerprint
                            or snapshot.get("quote")!=issue["quote"] or snapshot.get("category")!=issue["category"]):
                        continue
                    entry["discussions"][group].append({"id":comment["id"],"issue_id":comment["target_id"],
                        "quote":snapshot["quote"],"category":snapshot["category"],
                        "actor":comment["actor"],"body":comment["body"],"created_at":comment["created_at"],
                        "target_snapshot":copy.deepcopy(snapshot),"unverified":unverified})
            comparison=dict(entry)
            if not previous_materials_known:
                comparison.pop("previous_materials",None)
            entry["changes"]=review_changes(comparison)
            return entry
