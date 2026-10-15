"""Human-approved, project-scoped retrieval aliases."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

MAX_PAIRS = 20
_RISK = ("不", "无", "未", "全部", "所有", "普遍", "多数", "显著", "导致", "证明", "增加", "减少")


def validate_pairs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_PAIRS:
        raise ValueError(f"项目术语表最多 {MAX_PAIRS} 组。")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("术语映射格式不正确。")
        source = str(item.get("source") or "").strip().lower()
        target = str(item.get("target") or "").strip().lower()
        if (not 2 <= len(source) <= 30 or not 2 <= len(target) <= 30
                or source == target or source in seen
                or not re.fullmatch(r"[\w\u3400-\u9fff]+", source)
                or not re.fullmatch(r"[\w\u3400-\u9fff]+", target)
                or any(word in source or word in target for word in _RISK)):
            raise ValueError(f"术语映射不适合自动用于检索：{source} → {target}。请核对否定、数量和因果含义。")
        seen.add(source)
        result.append({"source": source, "target": target})
    return result


def load_pairs(project: Mapping[str, Any] | None) -> list[dict[str, str]]:
    try:
        raw = json.loads(str((project or {}).get("term_pairs_json") or "[]"))
        return validate_pairs(raw)
    except (ValueError, TypeError):
        return []
