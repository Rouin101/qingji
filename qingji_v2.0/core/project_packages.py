"""完整本地项目交接：校验后恢复独立副本，不合并或覆盖现有项目。

SHA-256 只检测包内容改变，不验证提供者身份，也不证明材料或判断真实。
包只包含青迹已保存的文字和关系，不包含服务配置或原上传文件二进制。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime

from core.collaboration import (MAX_ACTIVITY, MAX_COMMENTS, MAX_TASKS, assignee,
                                declared_actor, due_date, members_list, migrate,
                                record_activity, result_fingerprint, short_text)
from core.projects import document, material_list, now, text
from core.review import CATEGORIES, MAX_REPORT_CHARS, ReviewError

PACKAGE_FORMAT = "qingji-project"
SCHEMA_VERSION = 1
MAX_PACKAGE_BYTES = 12 * 1024 * 1024
MAX_REVISIONS = 100
IMPORT_WARNING = "外部交接副本；历史判断未在本机复核，请重新确认材料授权并复查。"

PROJECT_FIELDS = {"id", "name", "description", "version", "created_at", "updated_at",
                  "report", "materials", "review_materials", "result", "choices", "manual_text",
                  "reading_size", "tasks", "needs_review", "is_example", "members", "comments",
                  "activity", "activity_earlier_count", "archived", "archived_at", "imported_from"}
RESULT_FIELDS = {"mode", "report", "issues", "notices", "coverage", "used_material_ids"}
TASK_STATUSES = {"open", "material_added", "awaiting_confirmation", "done"}
SNAPSHOT_FIELDS = {"project": {"name"}, "task": {"action", "kind", "quote"},
                   "material": {"name", "source_role", "text_fingerprint"},
                   "issue": {"quote", "category", "result_fingerprint"}}


def _json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ReviewError("交接文件不是可读取的项目 JSON。") from exc


def _object(value, label):
    if not isinstance(value, dict):
        raise ReviewError(f"交接文件中的{label}不完整。")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ReviewError(f"交接文件中的{label}无效。")
    return value


def _timestamp(value, label, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or len(value) > 60:
        raise ReviewError(f"交接文件中的{label}无效。")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise ReviewError(f"交接文件中的{label}无效。") from exc
    return value


def _integer(value, label, minimum=0, maximum=1_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReviewError(f"交接文件中的{label}无效。")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise ReviewError(f"交接文件中的{label}无效。")
    return value


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ReviewError(f"交接文件中的{label}无效。")
    return value


def _materials(items):
    if not isinstance(items, list):
        raise ReviewError("交接文件中的材料列表不完整。")
    # material_list 会为缺失标识生成新 ID；交接关系不能依靠这种修复。
    for item in items:
        _object(item, "材料")
        if not _identifier(item.get("id"), "材料标识").startswith("m"):
            raise ReviewError("交接材料标识必须保持原有材料关系。")
    return material_list(items)


def _notes(value, label, count=40):
    if not isinstance(value, list) or len(value) > count:
        raise ReviewError(f"交接文件中的{label}不完整或过多。")
    return [text(item, label, 4000) for item in value]


def _result(value, materials):
    """独立核对原句和引用，不信任包中声称的检查成功标记。"""
    if value is None:
        return None
    _object(value, "核对结果")
    if set(value) - RESULT_FIELDS:
        raise ReviewError("交接文件包含不支持的核对结果字段。")
    if value.get("mode") not in {"ai", "preliminary", "example"}:
        raise ReviewError("交接文件中的检查方式无效。")
    raw_report = _object(value.get("report"), "核对正文")
    if set(raw_report) - {"id", "name", "text", "notes", "source_role", "context", "collected_at"}:
        raise ReviewError("交接文件包含不支持的核对正文字段。")
    report = document(raw_report)
    if not report["text"].strip():
        raise ReviewError("交接核对结果缺少正文。")
    coverages = {"submitted_text", "curated_example_only"}
    if value["mode"] == "preliminary":
        coverages.add("expression_scan_only")
    if value.get("coverage", "submitted_text") not in coverages:
        raise ReviewError("交接文件中的检查范围无效。")
    # 模型至多20条，服务说明至多4条；读取说明来自本轮正文/材料，不能误用固定40条截断。
    notice_limit = 24 + len(report["notes"]) + sum(len(m["notes"]) for m in materials)
    _notes(value.get("notices", []), "检查说明", count=notice_limit)
    issues = value.get("issues")
    # AI 输出限制是200条；本地规则扫描每个短句都可能生成位置，不能因此丢弃合法历史。
    # 本地条数仍受正文字符上限和完整包12MB限制约束，不截断任何记录。
    issue_limit = MAX_REPORT_CHARS if value["mode"] == "preliminary" else 200
    if not isinstance(issues, list) or len(issues) > issue_limit:
        raise ReviewError(f"交接核对记录不完整或超过{issue_limit}条。")
    documents = {"report": report, **{m["id"]: m for m in materials}}
    eligible = {m["id"] for m in materials if m["enabled"] and m["consent_status"] == "confirmed"}
    used = value.get("used_material_ids")
    if used is not None:
        if not isinstance(used, list) or len(set(used)) != len(used) or any(mid not in eligible for mid in used):
            raise ReviewError("交接核对结果的材料范围无法对应当时授权记录。")
        eligible = set(used)
    ids = set()
    for issue in issues:
        _object(issue, "结论记录")
        if set(issue) - {"id", "start", "end", "quote", "category", "reason", "next_step", "suggested_text", "citations", "support_status"}:
            raise ReviewError("交接文件包含不支持的结论字段。")
        ident = _identifier(issue.get("id"), "结论标识")
        if ident in ids:
            raise ReviewError("交接文件中的结论标识重复。")
        ids.add(ident)
        start = _integer(issue.get("start"), "原句位置", maximum=len(report["text"]))
        end = _integer(issue.get("end"), "原句位置", minimum=start + 1, maximum=len(report["text"]))
        quote = text(issue.get("quote"), "原句", MAX_REPORT_CHARS, False)
        if report["text"][start:end] != quote:
            raise ReviewError("交接文件中的结论无法对应原句。")
        if issue.get("category") not in CATEGORIES or issue.get("support_status", "pending") not in {"supported", "partial", "unsupported", "disagreement", "pending"}:
            raise ReviewError("交接文件中的结论类型或支持程度无效。")
        text(issue.get("reason"), "结论说明", 4000, False)
        text(issue.get("next_step"), "下一步建议", 4000, False)
        if issue.get("suggested_text") is not None:
            text(issue["suggested_text"], "候选表述", 4000, False)
        citations = issue.get("citations", [])
        if not isinstance(citations, list) or len(citations) > 20:
            raise ReviewError("交接文件中的引用不完整或过多。")
        for citation in citations:
            _object(citation, "引用")
            if set(citation) - {"document_id", "document_name", "start", "end", "quote", "relation"}:
                raise ReviewError("交接文件包含不支持的引用字段。")
            doc_id = citation.get("document_id")
            if not isinstance(doc_id, str) or doc_id not in documents or (doc_id != "report" and doc_id not in eligible):
                raise ReviewError("交接引用缺少当时已授权的原材料快照。")
            doc = documents[doc_id]
            first = _integer(citation.get("start"), "引用位置", maximum=len(doc["text"]))
            last = _integer(citation.get("end"), "引用位置", minimum=first + 1, maximum=len(doc["text"]))
            source_quote = text(citation.get("quote"), "引用文字", 12000, False)
            text(citation.get("document_name"), "引用来源名称", 200, False)
            if doc["text"][first:last] != source_quote:
                raise ReviewError("交接引用无法在当时材料中核对。")
            if citation.get("relation", "unclassified") not in {"support", "different", "context", "unclassified"}:
                raise ReviewError("交接文件中的证据关系无效。")
    # 不补默认字段，不改变合法结果的指纹，历史评论仍定位到原判断。
    return copy.deepcopy(value)


def _choices(value, result):
    ids = {issue["id"] for issue in (result or {}).get("issues", [])}
    if not isinstance(value, dict) or any(key not in ids or choice not in {"accepted", "kept"} for key, choice in value.items()):
        raise ReviewError("交接文件中的作者取舍无法对应结论。")
    return copy.deepcopy(value)


def _manual(value):
    return None if value is None else text(value, "编辑正文", MAX_REPORT_CHARS)


def _tasks(items, project, historical_material_ids=()):
    if not isinstance(items, list) or len(items) > MAX_TASKS:
        raise ReviewError("交接文件中的任务列表不完整或过多。")
    result, ids = [], set()
    materials = {m["id"] for m in project["materials"]} | set(historical_material_ids)
    for item in items:
        _object(item, "任务")
        ident = _identifier(item.get("id"), "任务标识")
        if ident in ids:
            raise ReviewError("交接文件中的任务标识重复。")
        ids.add(ident)
        kind = item.get("kind", "evidence")
        status = item.get("status")
        if kind not in {"evidence", "practice"} or status not in TASK_STATUSES:
            raise ReviewError("交接文件中的任务类型或状态无效。")
        mids = item.get("material_ids", [])
        if not isinstance(mids, list) or len(mids) > 8 or any(not isinstance(mid, str) or mid not in materials for mid in mids) or len(set(mids)) != len(mids):
            raise ReviewError("交接任务无法对应项目材料。")
        category = item.get("category", "实践任务" if kind == "practice" else "其他")
        if category not in CATEGORIES | {"实践任务"}:
            raise ReviewError("交接任务的结论类型无效。")
        task = {"id": ident, "kind": kind, "status": status, "material_ids": list(mids),
                "quote": text(item.get("quote", ""), "任务原句", MAX_REPORT_CHARS),
                "category": category, "action": short_text(item.get("action"), "任务内容", 4000, True),
                "assignee_id": assignee(project, item.get("assignee_id", "")),
                "due_date": due_date(item.get("due_date", "")),
                "notes": short_text(item.get("notes", ""), "任务记录", 3000),
                "created_at": _timestamp(item.get("created_at"), "任务创建时间")}
        for key in ("last_review_at", "confirmed_at", "imported_confirmed_at"):
            if key in item:
                task[key] = _timestamp(item[key], "任务记录时间")
        if "imported_status" in item:
            if item["imported_status"] not in TASK_STATUSES:
                raise ReviewError("交接任务原状态无效。")
            task["imported_status"] = item["imported_status"]
        result.append(task)
    return result


def _comments(items, project):
    if not isinstance(items, list) or len(items) > MAX_COMMENTS:
        raise ReviewError("交接文件中的讨论不完整或过多。")
    result, ids = [], set()
    for item in items:
        _object(item, "讨论")
        ident = _identifier(item.get("id"), "讨论标识")
        kind = item.get("target_type")
        target = _identifier(item.get("target_id"), "讨论对象标识")
        if ident in ids or kind not in SNAPSHOT_FIELDS:
            raise ReviewError("交接讨论的类型或标识无效。")
        ids.add(ident)
        snapshot = _object(item.get("target_snapshot"), "讨论对象快照")
        if set(snapshot) != SNAPSHOT_FIELDS[kind]:
            raise ReviewError("交接讨论缺少完整的原对象快照。")
        if kind == "project":
            if target != project["id"]:
                raise ReviewError("项目讨论不属于交接项目。")
            text(snapshot["name"], "讨论项目名称", 200, False)
        elif kind == "task":
            short_text(snapshot["action"], "讨论任务", 4000, True)
            text(snapshot["quote"], "讨论原句", MAX_REPORT_CHARS)
            if snapshot["kind"] not in {"practice", "evidence"}:
                raise ReviewError("讨论任务类型无效。")
        elif kind == "material":
            text(snapshot["name"], "讨论材料名称", 200, False)
            document({"name": snapshot["name"], "source_role": snapshot["source_role"]})
            _digest(snapshot["text_fingerprint"], "讨论材料指纹")
        else:
            text(snapshot["quote"], "讨论原句", MAX_REPORT_CHARS, False)
            if snapshot["category"] not in CATEGORIES:
                raise ReviewError("讨论结论类别无效。")
            _digest(snapshot["result_fingerprint"], "讨论判断指纹")
        # 历史对象可能已移除；保留快照，读取时重新判断归属，不挂到复用的 i1。
        result.append({"id": ident, "target_type": kind, "target_id": target,
                       "target_snapshot": copy.deepcopy(snapshot),
                       "body": short_text(item.get("body"), "讨论内容", 3000, True),
                       "actor": declared_actor(item.get("actor", "")),
                       "created_at": _timestamp(item.get("created_at"), "讨论时间")})
    return result


def _activity(items):
    if not isinstance(items, list) or len(items) > MAX_ACTIVITY:
        raise ReviewError("交接文件中的操作记录不完整或过多。")
    result, ids = [], set()
    for item in items:
        _object(item, "操作记录")
        ident = _identifier(item.get("id"), "操作记录标识")
        if ident in ids:
            raise ReviewError("交接操作记录标识重复。")
        ids.add(ident)
        result.append({"id": ident, "action": short_text(item.get("action"), "操作名称", 60, True),
                       "actor": declared_actor(item.get("actor", "")),
                       "created_at": _timestamp(item.get("created_at"), "操作时间"),
                       "detail": short_text(item.get("detail", ""), "操作说明", 3000)})
    return result


def _import_metadata(value):
    _object(value, "交接来源")
    fields = {"project_id", "project_name", "source_created_at", "source_updated_at",
              "exported_at", "imported_at", "actor", "warning"}
    if set(value) != fields:
        raise ReviewError("交接来源信息不完整。")
    _identifier(value["project_id"], "来源项目标识")
    text(value["project_name"], "来源项目名称", 200, False)
    declared_actor(value["actor"])
    text(value["warning"], "交接来源说明", 1000, False)
    for key in ("source_created_at", "source_updated_at", "exported_at", "imported_at"):
        _timestamp(value[key], "交接来源时间")
    return copy.deepcopy(value)


def _validated_payload(payload):
    _object(payload, "项目内容")
    if set(payload) != {"project", "revisions"}:
        raise ReviewError("交接项目的内容结构不完整。")
    source = migrate(copy.deepcopy(_object(payload["project"], "项目")))
    project = {key: source[key] for key in PROJECT_FIELDS if key in source}
    project["id"] = _identifier(source.get("id"), "项目标识")
    project["name"] = text(source.get("name"), "项目名称", 200, False)
    project["description"] = text(source.get("description", ""), "项目简介", 2000)
    project["version"] = _integer(source.get("version"), "项目版本", minimum=1)
    for key in ("created_at", "updated_at"):
        project[key] = _timestamp(source.get(key), "项目时间")
    project["report"] = document(_object(source.get("report"), "项目正文"))
    project["materials"] = _materials(source.get("materials"))
    project["members"] = members_list(source["members"])
    if any(not m.get("id") for m in source["members"]):
        raise ReviewError("交接成员缺少稳定标识。")
    project["comments"] = _comments(source["comments"], project)
    project["activity"] = _activity(source["activity"])
    project["activity_earlier_count"] = _integer(source["activity_earlier_count"], "较早操作数量")
    for key in ("needs_review", "is_example", "archived"):
        project[key] = _boolean(source.get(key), "项目状态")
    project["archived_at"] = _timestamp(source.get("archived_at"), "归档时间", True)
    if type(source.get("reading_size")) is not int or source["reading_size"] not in (16, 18, 20, 22):
        raise ReviewError("交接阅读字号无效。")
    project["reading_size"] = source["reading_size"]
    project["manual_text"] = _manual(source.get("manual_text"))
    if "imported_from" in source:
        project["imported_from"] = _import_metadata(source["imported_from"])

    revisions = payload["revisions"]
    if not isinstance(revisions, list) or len(revisions) > MAX_REVISIONS:
        raise ReviewError("交接文件最多包含100次完整核对历史。")
    validated, identities, contexts = [], set(), {}
    # 先校验每轮自己的正文/材料快照，再用于寻找旧结构的 previous_result 上下文。
    for revision in revisions:
        _object(revision, "检查历史")
        if set(revision) != {"id", "created_at", "data"}:
            raise ReviewError("交接检查历史的结构不完整。")
        ident = _identifier(revision["id"], "历史标识")
        if ident in identities:
            raise ReviewError("交接历史标识重复。")
        identities.add(ident)
        entry = _object(revision["data"], "历史正文")
        allowed = {"result", "materials", "choices", "previous_report", "previous_result",
                   "previous_materials", "previous_manual_text", "summary", "imported_unverified"}
        if set(entry) - allowed:
            raise ReviewError("交接文件包含不支持的历史字段。")
        mats = _materials(entry.get("materials"))
        reviewed = _result(entry.get("result"), mats)
        if reviewed is None:
            raise ReviewError("交接检查历史缺少完整判断。")
        contexts[result_fingerprint(reviewed)] = mats
        data = {"result": reviewed, "materials": mats,
                "previous_report": document(_object(entry.get("previous_report"), "前次正文")),
                "previous_result": copy.deepcopy(entry.get("previous_result")),
                "choices": copy.deepcopy(entry.get("choices", {})),
                "previous_manual_text": _manual(entry.get("previous_manual_text")),
                "summary": text(entry.get("summary"), "历史说明", 1000, False)}
        if "previous_materials" in entry:
            data["previous_materials"] = _materials(entry["previous_materials"])
        if "imported_unverified" in entry:
            data["imported_unverified"] = _boolean(entry["imported_unverified"], "历史来源状态")
        validated.append({"id": ident, "created_at": _timestamp(revision["created_at"], "历史时间"), "data": data})
    earlier_contexts = {}
    for revision in validated:
        entry = revision["data"]
        previous = entry["previous_result"]
        previous_mats = entry.get("previous_materials", earlier_contexts.get(result_fingerprint(previous), []))
        entry["previous_result"] = _result(previous, previous_mats)
        entry["choices"] = _choices(entry["choices"], previous)
        if previous is not None:
            entry["previous_materials"] = copy.deepcopy(previous_mats)
        earlier_contexts[result_fingerprint(entry["result"])] = entry["materials"]

    current = source.get("result")
    review_mats = source.get("review_materials")
    if review_mats is None:
        review_mats = contexts.get(result_fingerprint(current))
        if review_mats is None:
            # 当前材料不自动等于历史审阅材料；无法对应快照时不能冒充原依据。
            review_mats = []
    review_mats = _materials(review_mats)
    project["result"] = _result(current, review_mats)
    project["review_materials"] = review_mats
    project["choices"] = _choices(source.get("choices", {}), current)
    historical_ids = {m["id"] for revision in validated for key in ("materials", "previous_materials")
                      for m in revision["data"].get(key, [])} | {m["id"] for m in review_mats}
    project["tasks"] = _tasks(source.get("tasks"), project, historical_ids)
    return {"project": project, "revisions": validated}


def _checked_payload(payload):
    try:
        return _validated_payload(payload)
    except ReviewError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError) as exc:
        raise ReviewError("交接文件的字段类型或关系不完整，请使用完整项目交接文件。") from exc


def export_package(store, project_id):
    """原子读取项目与完整历史。超限拒绝，绝不静默只打包最近100次。"""
    _identifier(project_id, "项目标识")
    db = store.connect()
    try:
        db.execute("BEGIN")
        row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise ReviewError("找不到这个实践项目。")
        count = db.execute("SELECT COUNT(*) FROM revisions WHERE project_id=?", (project_id,)).fetchone()[0]
        if count > MAX_REVISIONS:
            raise ReviewError("项目超过100次检查历史，当前不能生成完整交接文件；原记录仍保留。")
        revisions = [{"id": ident, "created_at": stamp, "data": json.loads(content)}
                     for ident, stamp, content in db.execute("SELECT id,created_at,data FROM revisions WHERE project_id=? ORDER BY rowid", (project_id,))]
        project = migrate(json.loads(row[0]))
        # 白名单阻止服务配置或未来无关字段随数据库对象进入交接包。
        project = {key: value for key, value in project.items() if key in PROJECT_FIELDS}
        payload = _checked_payload({"project": project, "revisions": revisions})
        package = {"format": PACKAGE_FORMAT, "schema_version": SCHEMA_VERSION, "exported_at": now(),
                   "payload": payload, "sha256": hashlib.sha256(_json_bytes(payload)).hexdigest()}
        if len(_json_bytes(package)) > MAX_PACKAGE_BYTES:
            raise ReviewError("完整交接内容超过12 MB，当前不能生成交接文件；原记录仍保留。")
        return package
    finally:
        db.close()


def import_package(store, package, actor=""):
    """全部验证通过后一次事务写入新项目；任何失败都不覆盖现有项目。"""
    _object(package, "交接文件")
    if len(_json_bytes(package)) > MAX_PACKAGE_BYTES:
        raise ReviewError("交接文件请控制在12 MB以内。")
    if set(package) != {"format", "schema_version", "exported_at", "payload", "sha256"}:
        raise ReviewError("交接文件结构不完整。")
    if package["format"] != PACKAGE_FORMAT or type(package["schema_version"]) is not int or package["schema_version"] != SCHEMA_VERSION:
        raise ReviewError("不支持这个交接文件版本。")
    _timestamp(package["exported_at"], "交接导出时间")
    digest = _digest(package["sha256"], "完整性校验值")
    if digest != hashlib.sha256(_json_bytes(package["payload"])).hexdigest():
        raise ReviewError("交接文件完整性校验失败，请使用完整原文件；校验值不认证来源。")
    payload = _checked_payload(package["payload"])
    project = payload["project"]
    source_id, source_name = project["id"], project["name"]
    stamp = now()
    project["imported_from"] = {"project_id": source_id, "project_name": source_name,
                                "source_created_at": project["created_at"], "source_updated_at": project["updated_at"],
                                "exported_at": package["exported_at"], "imported_at": stamp,
                                "actor": declared_actor(actor), "warning": IMPORT_WARNING}
    project.update(id=uuid.uuid4().hex, name=source_name[:194] + "（交接副本）", version=1,
                   created_at=stamp, updated_at=stamp, needs_review=True, archived=False, archived_at=None)
    for material in project["materials"]:
        material["consent_status"] = "unconfirmed"
    for task in project["tasks"]:
        if task["kind"] == "evidence" and task["status"] == "done":
            task["imported_status"] = "done"
            if task.get("confirmed_at"):
                task["imported_confirmed_at"] = task.pop("confirmed_at")
            task["status"] = "awaiting_confirmation"
    for comment in project["comments"]:
        if comment["target_type"] == "project":
            comment["target_id"] = project["id"]
    record_activity(project, "imported", actor, stamp, "从交接文件恢复独立副本；重新确认授权并复查")
    db = store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO projects VALUES (?,?)", (project["id"], json.dumps(project, ensure_ascii=False)))
        for revision in payload["revisions"]:
            entry = revision["data"]
            entry["imported_unverified"] = True
            db.execute("INSERT INTO revisions VALUES (?,?,?,?)", (uuid.uuid4().hex, project["id"], revision["created_at"], json.dumps(entry, ensure_ascii=False)))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ReviewError("交接副本写入失败，现有项目未被覆盖，请重试。") from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return store.get(project["id"])
