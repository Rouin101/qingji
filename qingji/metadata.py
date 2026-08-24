"""Conservative metadata suggestions for imported text materials."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class MaterialMetadataSuggestion:
    """Metadata found in the material or filename, never a confirmed fact."""

    source_role: str | None = None
    context: str = ""
    captured_at: date | None = None
    signals: tuple[str, ...] = ()

    @property
    def has_suggestions(self) -> bool:
        return bool(self.source_role or self.context or self.captured_at)


_ROLE_LABELS = (
    ("正式记录", ("正式记录", "公开资料", "官网", "报告", "统计表", "文件")),
    ("工作人员", ("工作人员", "负责人", "干部", "法官", "书记", "官方")),
    ("调研团队观察员", ("现场观察", "观察员", "团队成员", "队员", "观察记录")),
    ("受访者", ("受访者", "访谈对象", "居民", "村民", "学生", "采访")),
    ("团队分析", ("团队分析", "研究者分析", "分析结论", "推测")),
)

_CONTEXT_LABELS = (
    "采集场景",
    "调研场景",
    "访谈场景",
    "活动场景",
    "采集地点",
    "调研地点",
    "访谈地点",
    "地点",
)

_DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*"
    r"(?P<month>0?[1-9]|1[0-2])\s*(?:月|[-/.])\s*"
    r"(?P<day>[12]\d|3[01]|0?[1-9])\s*日?"
)


def _clean_line(value: str, limit: int = 100) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" ：:;；,，。\t")
    return value[:limit].rstrip(" ：:;；,，。\t")


def _parse_date(text: str) -> date | None:
    for match in _DATE_PATTERN.finditer(text or ""):
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    return None


def _role_from_text(text: str, filename: str) -> tuple[str | None, str | None]:
    combined = f"{filename}\n{(text or '')[:6000]}"
    for role, hints in _ROLE_LABELS:
        if any(hint in combined for hint in hints):
            return role, "正文或文件名中的来源角色线索"
    return None, None


def _context_from_text(text: str) -> tuple[str, str | None]:
    lines = [line for line in re.split(r"\r?\n", text or "") if line.strip()]
    label_pattern = "|".join(re.escape(label) for label in _CONTEXT_LABELS)
    labelled = re.compile(
        rf"(?:^|[\s【\[(])(?:{label_pattern})\s*[：:]\s*(.{{3,100}})",
        flags=re.I,
    )
    for line in lines[:80]:
        match = labelled.search(line)
        if match:
            value = _clean_line(match.group(1))
            if value:
                return value, "正文中的场景/地点字段"

    for line in lines[:15]:
        candidate = _clean_line(line, limit=80)
        if (
            4 <= len(candidate) <= 80
            and any(term in candidate for term in ("调研", "访谈", "观察", "实践", "法院"))
        ):
            return candidate, "正文标题或前置说明线索"
    return "", None


def _context_from_filename(filename: str) -> tuple[str, str | None]:
    stem = _clean_line(Path(filename or "").stem, limit=80)
    if not stem:
        return "", None
    # Remove generic suffixes but retain locations and activity names.
    cleaned = re.sub(
        r"(?:项目材料|成果材料|成果报告|调研报告|调查报告|报告|记录|材料|正文|附件)$",
        "",
        stem,
    )
    cleaned = _clean_line(cleaned, limit=70)
    if len(cleaned) < 3 or not any(
        term in cleaned for term in ("调研", "访谈", "观察", "实践", "线上", "法院", "法治")
    ):
        return "", None
    return f"文件名线索：{cleaned}", "文件名中的地点/活动线索"


def infer_material_metadata(
    text: str,
    filename: str = "",
) -> MaterialMetadataSuggestion:
    """Extract conservative metadata suggestions from text and filename.

    The function intentionally returns ``None``/empty values when a field is
    not explicit enough.  Callers should show the suggestion for confirmation
    and keep a manual input path.
    """

    source_role, role_signal = _role_from_text(text, filename)
    context, context_signal = _context_from_text(text)
    if not context:
        context, context_signal = _context_from_filename(filename)
    captured_at = _parse_date(f"{filename}\n{(text or '')[:12000]}")

    signals = tuple(
        item
        for item in (role_signal, context_signal, "正文或文件名中的完整日期" if captured_at else None)
        if item
    )
    return MaterialMetadataSuggestion(
        source_role=source_role,
        context=context,
        captured_at=captured_at,
        signals=signals,
    )
