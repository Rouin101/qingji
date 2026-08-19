"""CSV import, validation, and persistence for project retrieval evaluations."""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Iterable, Mapping

from .retrieval_eval import RetrievalEvalCase, evaluate_retrieval


EVAL_CSV_COLUMNS = (
    "name",
    "category",
    "query",
    "expected_evidence_ids",
    "expect_no_relevant",
)
ALLOWED_EVAL_CATEGORIES = {
    "direct",
    "paraphrase",
    "zero_hit",
    "conflict",
    "custom",
}
MAX_EVAL_CASES = 100


def _parse_bool(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"true", "1", "yes", "y", "是"}:
        return True
    if normalized in {"", "false", "0", "no", "n", "否"}:
        return False
    raise ValueError(f"无法识别布尔值：{value}")


def _parse_evidence_ids(value: str) -> tuple[int, ...]:
    normalized = (value or "").strip()
    if not normalized:
        return ()
    tokens = [
        token
        for token in re.split(r"[,，;；\s]+", normalized)
        if token
    ]
    ids: list[int] = []
    for token in tokens:
        match = re.fullmatch(r"[Ee]?(\d+)", token)
        if match is None or int(match.group(1)) <= 0:
            raise ValueError(f"证据编号格式无效：{token}")
        evidence_id = int(match.group(1))
        if evidence_id not in ids:
            ids.append(evidence_id)
    return tuple(ids)


def parse_eval_csv(content: bytes | str) -> tuple[RetrievalEvalCase, ...]:
    """Parse a UTF-8 CSV into validated evaluation cases."""

    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("评测文件必须使用 UTF-8 编码。") from exc
    else:
        text = str(content)
    reader = csv.DictReader(io.StringIO(text))
    missing_columns = set(EVAL_CSV_COLUMNS) - set(reader.fieldnames or [])
    if missing_columns:
        raise ValueError(
            "评测 CSV 缺少列：" + "、".join(sorted(missing_columns))
        )

    cases: list[RetrievalEvalCase] = []
    names: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        name = (row.get("name") or "").strip()
        category = (row.get("category") or "").strip().lower()
        query = (row.get("query") or "").strip()
        if not name:
            raise ValueError(f"第 {row_number} 行缺少用例名称。")
        if len(name) > 80:
            raise ValueError(f"第 {row_number} 行用例名称不能超过 80 字。")
        if name in names:
            raise ValueError(f"用例名称重复：{name}")
        if category not in ALLOWED_EVAL_CATEGORIES:
            raise ValueError(
                f"第 {row_number} 行类别无效：{category or '空'}。"
            )
        if not query:
            raise ValueError(f"第 {row_number} 行缺少检索查询。")
        if len(query) > 500:
            raise ValueError(f"第 {row_number} 行查询不能超过 500 字。")
        expected_ids = _parse_evidence_ids(
            row.get("expected_evidence_ids") or ""
        )
        expect_no_relevant = _parse_bool(
            row.get("expect_no_relevant") or ""
        )
        if expect_no_relevant and expected_ids:
            raise ValueError(
                f"第 {row_number} 行不能同时要求零命中和指定目标证据。"
            )
        if not expect_no_relevant and not expected_ids:
            raise ValueError(
                f"第 {row_number} 行必须填写目标证据编号，或设为零命中。"
            )
        cases.append(
            RetrievalEvalCase(
                name=name,
                category=category,
                query=query,
                expected_evidence_ids=expected_ids,
                expect_no_relevant=expect_no_relevant,
            )
        )
        names.add(name)
        if len(cases) > MAX_EVAL_CASES:
            raise ValueError(f"单次最多导入 {MAX_EVAL_CASES} 个评测用例。")
    if not cases:
        raise ValueError("评测 CSV 中没有可运行的用例。")
    return tuple(cases)


def build_eval_template(
    evidence_rows: Iterable[Mapping[str, Any]],
) -> bytes:
    """Build a project-aware UTF-8-BOM CSV template."""

    eligible = [
        row
        for row in evidence_rows
        if row.get("review_status") == "approved"
        and row.get("consent_status") == "confirmed"
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EVAL_CSV_COLUMNS)
    writer.writeheader()
    if eligible:
        evidence_id = int(eligible[0]["id"])
        writer.writerow(
            {
                "name": "示例_目标证据",
                "category": "custom",
                "query": f"请替换为希望召回 E{evidence_id} 的查询",
                "expected_evidence_ids": f"E{evidence_id}",
                "expect_no_relevant": "false",
            }
        )
    writer.writerow(
        {
            "name": "示例_零命中",
            "category": "zero_hit",
            "query": "请替换为与当前材料无关的查询",
            "expected_evidence_ids": "",
            "expect_no_relevant": "true",
        }
    )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def run_project_retrieval_eval(
    db: Any,
    project_id: int,
    cases: tuple[RetrievalEvalCase, ...],
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    """Validate project-local target IDs, run evaluation, and persist it."""

    project = db.get_project(int(project_id))
    if project is None:
        raise ValueError("当前项目不存在或已被删除。")
    evidence_rows = db.list_evidence_cards(int(project_id))
    rows_by_id = {int(row["id"]): row for row in evidence_rows}
    for case in cases:
        for evidence_id in case.expected_evidence_ids:
            row = rows_by_id.get(int(evidence_id))
            if row is None:
                raise ValueError(
                    f"用例“{case.name}”引用的 E{evidence_id} 不属于当前项目。"
                )
            if row.get("review_status") != "approved":
                raise ValueError(
                    f"用例“{case.name}”引用的 E{evidence_id} 尚未人工批准。"
                )
            if row.get("consent_status") != "confirmed":
                raise ValueError(
                    f"用例“{case.name}”引用的 E{evidence_id} 来源尚未确认授权。"
                )

    report = evaluate_retrieval(
        db, int(project_id), top_k=top_k, cases=cases
    )
    run_id = db.create_agent_run(
        int(project_id),
        "retrieval_eval",
        input_data={
            "top_k": top_k,
            "cases": [
                {
                    "name": case.name,
                    "category": case.category,
                    "query": case.query,
                    "expected_evidence_ids": list(
                        case.expected_evidence_ids
                    ),
                    "expect_no_relevant": case.expect_no_relevant,
                }
                for case in cases
            ],
        },
        output_data=report,
    )
    return {**report, "run_id": run_id}
