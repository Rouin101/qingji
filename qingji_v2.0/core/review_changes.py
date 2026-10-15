"""历史核对的只读变化摘要；不推断改写语义，也不把提示减少当作通过。"""

from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher


def _issues(result):
    return [i for i in result.get("issues", []) if isinstance(i, dict) and isinstance(i.get("quote"), str)
            and i["quote"]] if isinstance(result.get("issues", []), list) else []


def _text(result):
    report = result.get("report")
    return report.get("text") if isinstance(report, dict) and isinstance(report.get("text"), str) else None


def _position(issue, report):
    start, end = issue.get("start"), issue.get("end")
    if (isinstance(report, str) and type(start) is int and type(end) is int and
            0 <= start < end <= len(report) and report[start:end] == issue["quote"]):
        return start, end
    return None


def _single_occurrence(text, quote):
    first = text.find(quote) if isinstance(text, str) else -1
    return first >= 0 and text.find(quote, first + 1) < 0


def _record(issue):
    return {k: issue.get(k, "pending" if k == "support_status" else "")
            for k in ("quote", "start", "end", "category", "support_status")}


def _citation_signature(issue):
    citations = issue.get("citations", [])
    if not isinstance(citations, list):
        return ()
    # 次序改变不等于依据改变；重复次数、位置和关系改变都保留。
    return tuple(sorted(Counter(tuple(str(c.get(k, "unclassified" if k == "relation" else ""))
                                     for k in ("document_id", "start", "end", "quote", "relation", "document_name"))
                                for c in citations if isinstance(c, dict)).items()))


def _record_changes(previous, current):
    old, new = _issues(previous), _issues(current)
    old_text, new_text = _text(previous), _text(current)
    old_groups, new_groups = defaultdict(list), defaultdict(list)
    for index, issue in enumerate(old):
        old_groups[issue["quote"]].append(index)
    for index, issue in enumerate(new):
        new_groups[issue["quote"]].append(index)
    paired_old, paired_new, ambiguous_old, ambiguous_new = set(), set(), set(), set()
    pairs = []
    for quote in old_groups.keys() & new_groups.keys():
        before, after = old_groups[quote], new_groups[quote]
        unique = (len(before) == len(after) == 1 and _single_occurrence(old_text, quote)
                  and _single_occurrence(new_text, quote))
        if unique and _position(old[before[0]], old_text) and _position(new[after[0]], new_text):
            candidates = [(before[0], after[0])]
        elif isinstance(old_text, str) and old_text == new_text:
            old_positions = defaultdict(list)
            new_positions = defaultdict(list)
            for index in before:
                position = _position(old[index], old_text)
                if position:
                    old_positions[position].append(index)
            for index in after:
                position = _position(new[index], new_text)
                if position:
                    new_positions[position].append(index)
            candidates = [(old_positions[pos][0], new_positions[pos][0])
                          for pos in old_positions.keys() & new_positions.keys()
                          if len(old_positions[pos]) == len(new_positions[pos]) == 1]
        else:
            candidates = []
        for left, right in candidates:
            paired_old.add(left)
            paired_new.add(right)
            pairs.append((left, right))
        ambiguous_old.update(set(before) - paired_old)
        ambiguous_new.update(set(after) - paired_new)
    changes = []
    for left, right in sorted(pairs, key=lambda pair: new[pair[1]].get("start", 0)):
        before, after = old[left], new[right]
        fields = []
        for field in ("support_status", "category", "reason", "suggested_text", "next_step"):
            old_value = before.get(field, "pending" if field == "support_status" else "")
            new_value = after.get(field, "pending" if field == "support_status" else "")
            if old_value != new_value:
                fields.append({"field": field, "before": old_value, "after": new_value})
        if _citation_signature(before) != _citation_signature(after):
            fields.append({"field": "citations", "before": before.get("citations", []),
                           "after": after.get("citations", [])})
        if fields:
            changes.append({"quote": after["quote"], "previous_position": list(_position(before, old_text)),
                            "current_position": list(_position(after, new_text)), "fields": fields})
    return {"available": True, "matched_count": len(pairs), "changed": changes,
            "listed_new": [_record(issue) for index, issue in enumerate(new)
                           if index not in paired_new | ambiguous_new],
            "no_longer_listed": [_record(issue) for index, issue in enumerate(old)
                                 if index not in paired_old | ambiguous_old],
            "ambiguous_previous": [_record(old[index]) for index in sorted(ambiguous_old)],
            "ambiguous_current": [_record(new[index]) for index in sorted(ambiguous_new)]}


def _report_changes(previous, current):
    old, new = _text(previous), _text(current)
    if old is None or new is None:
        return {"available": False}
    before, after = old.splitlines(), new.splitlines()
    # 先去掉相同头尾；长篇重复行避免二次复杂度阻塞读取历史。
    left = 0
    while left < min(len(before), len(after)) and before[left] == after[left]:
        left += 1
    right = 0
    while right < min(len(before), len(after)) - left and before[-right - 1] == after[-right - 1]:
        right += 1
    old_middle = before[left:len(before) - right if right else len(before)]
    new_middle = after[left:len(after) - right if right else len(after)]
    added = removed = modified = 0
    for kind, i, j, a, b in SequenceMatcher(a=old_middle, b=new_middle,
                                           autojunk=max(len(old_middle), len(new_middle)) > 2000).get_opcodes():
        if kind == "replace":
            modified += min(j - i, b - a)
            removed += max(0, (j - i) - (b - a))
            added += max(0, (b - a) - (j - i))
        elif kind == "delete":
            removed += j - i
        elif kind == "insert":
            added += b - a
    return {"available": True, "changed": old != new, "added_lines": added, "removed_lines": removed,
            "modified_lines": modified, "previous_lines": len(before), "current_lines": len(after)}


def _material_changes(entry):
    before, after = entry.get("previous_materials"), entry.get("materials")
    if not isinstance(before, list) or not isinstance(after, list):
        return {"available": False, "added": [], "removed": [], "changed": []}
    old = {m["id"]: m for m in before if isinstance(m, dict) and isinstance(m.get("id"), str)}
    new = {m["id"]: m for m in after if isinstance(m, dict) and isinstance(m.get("id"), str)}
    compact = lambda material: {"id": material["id"], "name": material.get("name", "未命名材料")}
    changed = []
    for identity in old.keys() & new.keys():
        fields = []
        for field in ("name", "text", "consent_status", "enabled", "tags", "notes"):
            default = True if field == "enabled" else "unconfirmed" if field == "consent_status" else [] if field in {"tags", "notes"} else ""
            if old[identity].get(field, default) != new[identity].get(field, default):
                fields.append(field)
        if any(old[identity].get(field, "待确认" if field == "source_role" else "") !=
               new[identity].get(field, "待确认" if field == "source_role" else "")
               for field in ("source_role", "context", "collected_at")):
            fields.append("source")
        if fields:
            changed.append(compact(new[identity]) | {"fields": fields})
    return {"available": True, "added": [compact(m) for identity, m in new.items() if identity not in old],
            "removed": [compact(m) for identity, m in old.items() if identity not in new],
            "changed": sorted(changed, key=lambda m: m["id"])}


def _scope(result):
    value = result.get("used_material_ids")
    if not isinstance(value, list) or any(not isinstance(i, str) for i in value) or len(set(value)) != len(value):
        return None
    return list(value)


def review_changes(entry):
    """返回读取视图，输入 entry、数据库与原始备份均保持不变。"""
    current = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    previous = entry.get("previous_result")
    if not isinstance(previous, dict):
        notes = ["本轮记录已保存；没有关联的前次判断，不将全部内容标为新增或已解决。"]
        if entry.get("imported_unverified"):
            notes.append("外部历史，未在本机复核；摘要仅比较已交接的记录。")
        return {"baseline_available": False, "summary": "暂无可比较的前次判断", "report": {"available": False},
                "materials": {"available": False, "added": [], "removed": [], "changed": []},
                "scope": {"previous_known": False, "current_known": _scope(current) is not None,
                          "previous_ids": None, "current_ids": _scope(current), "changed": None},
                "records": {"available": False},
                "notes": notes}
    report = _report_changes(previous, current)
    materials = _material_changes(entry)
    old_scope, new_scope = _scope(previous), _scope(current)
    scope = {"previous_known": old_scope is not None, "current_known": new_scope is not None,
             "previous_ids": old_scope, "current_ids": new_scope,
             "changed": set(old_scope) != set(new_scope) if old_scope is not None and new_scope is not None else None}
    records = _record_changes(previous, current)
    parts, notes = [], []
    if report.get("changed"):
        count = sum(report[k] for k in ("added_lines", "removed_lines", "modified_lines"))
        parts.append(f"正文{count}行调整" if count else "正文换行变化")
    material_count = sum(len(materials[k]) for k in ("added", "removed", "changed"))
    if material_count:
        parts.append(f"材料{material_count}份变化")
    if scope["changed"]:
        parts.append("记录的纳入范围变化")
    elif scope["changed"] is None:
        parts.append("部分历史纳入范围未记录")
    record_count = sum(len(records[k]) for k in ("changed", "listed_new", "no_longer_listed"))
    if record_count:
        parts.append(f"原句记录{record_count}条变化")
    if records["ambiguous_previous"] or records["ambiguous_current"]:
        parts.append("部分原句无法自动配对")
    if previous.get("mode") != current.get("mode"):
        parts.append("核对方式变化")
    if not report["available"]:
        notes.append("缺少可比较的报告文字快照。")
    if not materials["available"]:
        notes.append("前后材料快照不完整，未将缺少快照解释为材料全部新增或移除。")
    if scope["changed"] is None:
        notes.append("部分历史未记录纳入材料范围，不能按授权状态倒推当时实际范围。")
    if records["ambiguous_previous"] or records["ambiguous_current"]:
        notes.append("重复或位置不明的原句无法可靠配对；不依靠结论编号猜测归属。")
    notes.append("不再列出或提示减少不代表问题已解决，也不表示结论更可靠。")
    if "preliminary" in {previous.get("mode"), current.get("mode")}:
        notes.append("本地预检只定位表达，待核对不等于依据不足。")
    if entry.get("imported_unverified"):
        notes.append("外部历史，未在本机复核；摘要仅比较已交接的记录。")
    return {"baseline_available": True, "summary": " · ".join(parts) or "已记录内容未发现变化",
            "report": report, "materials": materials, "scope": scope, "records": records, "notes": notes}
