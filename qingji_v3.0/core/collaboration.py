"""本地协作校验。成员与署名用于分工追溯，不代表登录或访问权限。"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from core.review import ReviewError

MAX_MEMBERS = 30
MAX_COMMENTS = 500
MAX_ACTIVITY = 200
MAX_TASKS = 200


def short_text(value, label, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ReviewError(f"{label}不完整或过长。")
    return value.strip()


def declared_actor(value=""):
    """只记录声明的姓名，不从该值推断成员权限。"""
    return short_text(value, "操作署名", 60) or "未署名"


def due_date(value=""):
    value = short_text(value, "任务日期", 10)
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise ReviewError("任务日期请使用有效的 YYYY-MM-DD 格式。") from exc
    return value


def material_tags(items):
    if not isinstance(items, list) or len(items)>12:
        raise ReviewError("每份材料最多保存 12 个标签。")
    result=[]
    for item in items:
        value=short_text(item,"材料标签",24)
        if value and value not in result:
            result.append(value)
    return result


def members_list(items):
    if not isinstance(items, list) or len(items) > MAX_MEMBERS:
        raise ReviewError(f"每个项目目前最多记录 {MAX_MEMBERS} 位成员。")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ReviewError("成员信息不完整。")
        member_id = item.get("id", "")
        if not isinstance(member_id, str) or len(member_id) > 80 or (member_id and member_id != member_id.strip()):
            raise ReviewError("成员标识无效。")
        result.append({"id": member_id or "u" + uuid.uuid4().hex,
                       "name": short_text(item.get("name", ""), "成员姓名", 60, True),
                       "role": short_text(item.get("role", ""), "成员分工", 40)})
    if len({m["id"] for m in result}) != len(result):
        raise ReviewError("成员标识不能重复。")
    if len({m["name"].casefold() for m in result}) != len(result):
        raise ReviewError("成员姓名重复，请增加可区分的称呼。")
    return result


def assignee(project, value=""):
    value = short_text(value, "任务负责人", 80)
    if value and not any(m["id"] == value for m in project["members"]):
        raise ReviewError("任务负责人已不在这个项目中，请重新选择。")
    return value


def migrate(project):
    """在本版 JSON 项目中补默认字段；无需读取或改写旧版数据库。"""
    project.setdefault("members", [])
    project.setdefault("comments", [])
    project.setdefault("activity", [])
    project.setdefault("activity_earlier_count", 0)
    project.setdefault("archived", False)
    project.setdefault("archived_at", None)
    for material in project.get("materials", []):
        material.setdefault("tags", [])
    for task in project.get("tasks", []):
        task.setdefault("kind", "evidence")
        task.setdefault("assignee_id", "")
        task.setdefault("due_date", "")
        task.setdefault("notes", "")
    return project


def record_activity(project, action, actor, created_at, detail=""):
    project["activity"].append({"id": uuid.uuid4().hex, "action": action,
                                "actor": declared_actor(actor), "created_at": created_at,
                                "detail": detail})
    excess = len(project["activity"]) - MAX_ACTIVITY
    if excess > 0:
        project["activity"] = project["activity"][excess:]
        project["activity_earlier_count"] += excess


def result_fingerprint(result):
    if not result:
        return ""
    return hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def pending_author_edits(project):
    """作者显示的正文是否已离开本轮审阅原文；手动正文优先于逐句取舍。"""
    result = project.get("result") or {}
    report_text = (result.get("report") or project.get("report") or {}).get("text", "")
    manual = project.get("manual_text")
    if manual is not None:
        return manual != report_text
    choices = project.get("choices", {})
    return any(choices.get(issue["id"]) == "accepted" and issue.get("suggested_text")
               and issue["suggested_text"] != issue["quote"] for issue in result.get("issues", []))


def reopen_completed_evidence(project, actor, created_at, reason):
    """原确认属于旧资料范围；重新打开补证任务，保留原确认时间及独立实践分工。"""
    reopened = 0
    for task in project["tasks"]:
        if task["kind"] == "evidence" and task["status"] == "done":
            task["status"] = "open"
            reopened += 1
    if reopened:
        record_activity(project, "evidence_reopened", actor, created_at,
                        f"{reason}，重新打开 {reopened} 项补证任务；原确认时间保留。")


def target_snapshot(project, target_type, target_id, fingerprint=None):
    target_type = short_text(target_type, "讨论对象", 20, True)
    target_id = short_text(target_id, "讨论对象标识", 80)
    if target_type == "project" and target_id in {"", project["id"]}:
        return project["id"], {"name": project["name"]}
    if target_type == "task":
        item = next((t for t in project["tasks"] if t["id"] == target_id), None)
        if item:
            return target_id, {"action": item["action"], "kind": item["kind"], "quote": item.get("quote", "")}
    elif target_type == "material":
        item = next((m for m in project["materials"] if m["id"] == target_id), None)
        if item:
            return target_id, {"name": item["name"], "source_role": item["source_role"],
                               "text_fingerprint": hashlib.sha256(item["text"].encode("utf-8")).hexdigest()}
    elif target_type == "issue":
        item = next((i for i in (project["result"] or {}).get("issues", []) if i["id"] == target_id), None)
        if item:
            return target_id, {"quote": item["quote"], "category": item["category"],
                               "result_fingerprint": result_fingerprint(project["result"]) if fingerprint is None else fingerprint}
    else:
        raise ReviewError("讨论对象类型无效。")
    raise ReviewError("讨论对象已变化或不属于这个项目，请查看最新记录。")


def comment_state(project, comment, snapshots=None, fingerprint=None):
    """读取时重新判断归属，旧 issue ID 的复用不会把讨论挂到新结论上。"""
    try:
        key=(comment["target_type"],comment["target_id"])
        if snapshots is not None and key in snapshots:
            current=snapshots[key]
        else:
            _, current = target_snapshot(project, comment["target_type"], comment["target_id"], fingerprint)
            if snapshots is not None:
                snapshots[key]=current
    except ReviewError:
        return "removed"
    previous = comment["target_snapshot"]
    if comment["target_type"] == "issue" and current != previous:
        return "historical"
    if comment["target_type"] == "material" and current != previous:
        return "changed"
    if comment["target_type"] == "task" and current != previous:
        return "changed"
    return "current"


def with_comment_states(project):
    value = copy.deepcopy(project)
    snapshots={}
    fingerprint=result_fingerprint(project["result"]) if any(c["target_type"]=="issue" for c in project["comments"]) else None
    for comment in value["comments"]:
        comment["target_state"] = comment_state(project, comment, snapshots, fingerprint)
    return value


def overdue_count(project):
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    return sum(t["status"] != "done" and bool(t.get("due_date")) and t["due_date"] < today
               for t in project["tasks"])
