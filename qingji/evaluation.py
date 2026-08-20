"""CSV import, validation, and persistence for project retrieval evaluations."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from typing import Any, Iterable, Mapping

from .diagnostics import RETRIEVAL_DIAGNOSTIC_VERSION
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
MAX_EVAL_FILE_BYTES = 1024 * 1024

EVAL_EXPORT_COLUMNS = (
    "run_id",
    "created_at",
    "case_set_id",
    "evidence_set_id",
    "retrieval_version",
    "top_k",
    "relevance_threshold",
    "result",
    "name",
    "category",
    "query",
    "expected_evidence_ids",
    "expect_no_relevant",
    "expected_id_ranks",
    "relevant_evidence_ids",
    "relevant_count",
)


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
        if len(content) > MAX_EVAL_FILE_BYTES:
            raise ValueError("评测 CSV 不能超过 1 MiB。")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("评测文件必须使用 UTF-8 编码。") from exc
    else:
        text = str(content).lstrip("\ufeff")
        if len(text.encode("utf-8")) > MAX_EVAL_FILE_BYTES:
            raise ValueError("评测 CSV 不能超过 1 MiB。")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    if len(fieldnames) != len(set(fieldnames)):
        raise ValueError("评测 CSV 表头包含重复列。")
    missing_columns = set(EVAL_CSV_COLUMNS) - set(fieldnames)
    if missing_columns:
        raise ValueError(
            "评测 CSV 缺少列：" + "、".join(sorted(missing_columns))
        )

    cases: list[RetrievalEvalCase] = []
    names: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(
                f"第 {row_number} 行列数超过表头，请检查未转义的逗号。"
            )
        values = [row.get(column) for column in EVAL_CSV_COLUMNS]
        if any(value is not None and not isinstance(value, str) for value in values):
            raise ValueError(f"第 {row_number} 行包含无法识别的单元格。")
        if not any((value or "").strip() for value in values):
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


def _normalized_case_payload(case: RetrievalEvalCase | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(case, RetrievalEvalCase):
        name = case.name
        category = case.category
        query = case.query
        expected_ids = case.expected_evidence_ids
        expect_no_relevant = case.expect_no_relevant
    else:
        name = case.get("name", "")
        category = case.get("category", "")
        query = case.get("query", "")
        expected_ids = case.get("expected_evidence_ids") or []
        raw_zero_hit = case.get("expect_no_relevant", False)
        expect_no_relevant = (
            _parse_bool(raw_zero_hit)
            if isinstance(raw_zero_hit, str)
            else bool(raw_zero_hit)
        )
    normalized_ids: list[int] = []
    for item in expected_ids:
        try:
            evidence_id = int(item)
        except (TypeError, ValueError):
            continue
        if evidence_id > 0 and evidence_id not in normalized_ids:
            normalized_ids.append(evidence_id)
    return {
        "name": str(name or "").strip(),
        "category": str(category or "").strip().lower(),
        "query": str(query or "").strip(),
        "expected_evidence_ids": sorted(normalized_ids),
        "expect_no_relevant": bool(expect_no_relevant),
    }


def build_eval_case_set_id(
    cases: Iterable[RetrievalEvalCase | Mapping[str, Any]],
) -> str:
    """Return an order-independent fingerprint for one evaluation case set."""

    normalized = [_normalized_case_payload(case) for case in cases]
    normalized.sort(
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"cs_{digest}"


def build_evidence_set_id(
    evidence_rows: Iterable[Mapping[str, Any]],
) -> str:
    """Fingerprint the exact approved, authorized corpus used by retrieval.

    The payload includes every field read by ``_candidate_text`` plus the card
    id used as the deterministic ranking tie-breaker.  Rows outside the
    retrievable set are excluded, so approving, withdrawing, adding, removing,
    or editing a retrieval-relevant card changes the fingerprint.
    """

    normalized: list[dict[str, Any]] = []
    for row in evidence_rows:
        review_status = str(
            getattr(row.get("review_status"), "value", row.get("review_status"))
            or ""
        )
        consent_status = str(
            getattr(row.get("consent_status"), "value", row.get("consent_status"))
            or ""
        )
        if review_status != "approved" or consent_status != "confirmed":
            continue
        try:
            evidence_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("可检索证据缺少有效编号。") from exc
        normalized.append(
            {
                "id": evidence_id,
                "title": str(row.get("title") or ""),
                "quote": str(row.get("quote") or ""),
                "summary": str(row.get("summary") or ""),
                "context": str(row.get("context") or ""),
                "source_role": str(row.get("source_role") or ""),
                "review_status": review_status,
                "consent_status": consent_status,
            }
        )
    normalized.sort(
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"es_{digest}"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _eval_run_metadata(run: Mapping[str, Any]) -> dict[str, Any]:
    input_data = _mapping(run.get("input"))
    output = _mapping(run.get("output"))
    raw_results = output.get("results")
    results = [dict(item) for item in raw_results or [] if isinstance(item, Mapping)]
    raw_cases = input_data.get("cases")
    cases = [dict(item) for item in raw_cases or [] if isinstance(item, Mapping)]
    case_set_id = str(
        output.get("case_set_id") or input_data.get("case_set_id") or ""
    )
    if not case_set_id and cases:
        case_set_id = build_eval_case_set_id(cases)
    evidence_set_id = str(
        output.get("evidence_set_id") or input_data.get("evidence_set_id") or ""
    )
    case_count = _integer(output.get("case_count"), len(results) or len(cases))
    passed_count = _integer(
        output.get("passed_count", output.get("hit_count")),
        sum(bool(item.get("passed", item.get("hit"))) for item in results),
    )
    default_rate = passed_count / case_count if case_count else 0.0
    pass_rate = _number(
        output.get("pass_rate", output.get("hit_rate")), default_rate
    )
    threshold_value = output.get(
        "relevance_threshold", input_data.get("relevance_threshold")
    )
    threshold = (
        _number(threshold_value) if threshold_value not in (None, "") else None
    )
    categories = {
        str(name): _mapping(summary)
        for name, summary in _mapping(output.get("categories")).items()
    }
    return {
        "run_id": _integer(run.get("id", run.get("run_id"))),
        "created_at": str(run.get("created_at") or ""),
        "case_set_id": case_set_id or "未记录",
        "evidence_set_id": evidence_set_id or "未记录",
        "retrieval_version": str(
            output.get("retrieval_version")
            or input_data.get("retrieval_version")
            or "未记录"
        ),
        "top_k": _integer(output.get("top_k", input_data.get("top_k"))),
        "relevance_threshold": threshold,
        "case_count": case_count,
        "passed_count": passed_count,
        "pass_rate": pass_rate,
        "categories": categories,
        "results": results,
        "cases": cases,
        "input": input_data,
        "output": output,
    }


def build_eval_history_rows(
    runs: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize runs and compare only identical evaluation configurations."""

    rows = [_eval_run_metadata(run) for run in runs]
    rows.sort(key=lambda row: row["run_id"], reverse=True)
    for index, row in enumerate(rows):
        comparable_key = (
            row["case_set_id"],
            row["evidence_set_id"],
            row["retrieval_version"],
            row["top_k"],
            row["relevance_threshold"],
        )
        complete_key = (
            row["case_set_id"] != "未记录"
            and row["evidence_set_id"] != "未记录"
            and row["retrieval_version"] != "未记录"
            and row["top_k"] > 0
            and row["relevance_threshold"] is not None
        )
        older = next(
            (
                candidate
                for candidate in rows[index + 1 :]
                if complete_key
                and (
                    candidate["case_set_id"],
                    candidate["evidence_set_id"],
                    candidate["retrieval_version"],
                    candidate["top_k"],
                    candidate["relevance_threshold"],
                )
                == comparable_key
            ),
            None,
        )
        if older is not None:
            row["comparison_status"] = "可直接比较"
            row["comparable_to_run_id"] = older["run_id"]
            row["pass_rate_delta"] = row["pass_rate"] - older["pass_rate"]
        elif complete_key:
            row["comparison_status"] = "无可比历史"
            row["comparable_to_run_id"] = None
            row["pass_rate_delta"] = None
        elif row["evidence_set_id"] == "未记录":
            row["comparison_status"] = "证据集未记录，无法比较"
            row["comparable_to_run_id"] = None
            row["pass_rate_delta"] = None
        else:
            row["comparison_status"] = "配置未完整记录"
            row["comparable_to_run_id"] = None
            row["pass_rate_delta"] = None
    return rows


def _safe_csv_cell(value: Any) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (list, tuple, set)):
        text = ";".join(str(item) for item in value)
    else:
        text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def export_eval_run_csv(run: Mapping[str, Any]) -> bytes:
    """Export one persisted evaluation run as Excel-safe UTF-8-BOM CSV."""

    meta = _eval_run_metadata(run)
    cases_by_name = {
        str(case.get("name") or ""): case for case in meta["cases"]
    }
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EVAL_EXPORT_COLUMNS)
    writer.writeheader()
    for result in meta["results"]:
        name = str(result.get("name") or "")
        input_case = cases_by_name.get(name, {})
        expected_ids = result.get("expected_evidence_ids") or input_case.get(
            "expected_evidence_ids"
        ) or []
        expected_ranks = _mapping(result.get("expected_id_ranks"))
        row = {
            "run_id": meta["run_id"],
            "created_at": meta["created_at"],
            "case_set_id": meta["case_set_id"],
            "evidence_set_id": meta["evidence_set_id"],
            "retrieval_version": meta["retrieval_version"],
            "top_k": meta["top_k"],
            "relevance_threshold": meta["relevance_threshold"],
            "result": "passed" if result.get("passed", result.get("hit")) else "failed",
            "name": name,
            "category": result.get("category") or input_case.get("category", ""),
            "query": result.get("query") or input_case.get("query", ""),
            "expected_evidence_ids": ";".join(f"E{item}" for item in expected_ids),
            "expect_no_relevant": result.get(
                "expect_no_relevant", input_case.get("expect_no_relevant", False)
            ),
            "expected_id_ranks": ";".join(
                f"E{key}:{value if value is not None else 'not_retrieved'}"
                for key, value in expected_ranks.items()
            ),
            "relevant_evidence_ids": ";".join(
                f"E{item}" for item in result.get("relevant_evidence_ids") or []
            ),
            "relevant_count": result.get("relevant_count", 0),
        }
        writer.writerow({key: _safe_csv_cell(value) for key, value in row.items()})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _markdown_cell(value: Any) -> str:
    text = html.escape(
        str(value if value not in (None, "") else "—"), quote=False
    )
    return (
        text
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def export_eval_run_markdown(
    run: Mapping[str, Any], project_name: str
) -> str:
    """Export one persisted run with its comparison boundary kept explicit."""

    meta = _eval_run_metadata(run)
    threshold_label = (
        meta["relevance_threshold"]
        if meta["relevance_threshold"] is not None
        else "未记录"
    )
    lines = [
        f"# 青迹检索评测｜{_markdown_cell(project_name)}",
        "",
        "> 检索评测通过率只说明当前授权、已审核证据集下的本地检索表现，"
        "不是事实正确率，也不是外部基准成绩。",
        "",
        f"- 运行编号：R{meta['run_id']}",
        f"- 运行时间：{_markdown_cell(meta['created_at'])}",
        f"- 用例集：{_markdown_cell(meta['case_set_id'])}",
        f"- 证据集：{_markdown_cell(meta['evidence_set_id'])}",
        f"- 检索版本：{_markdown_cell(meta['retrieval_version'])}",
        f"- Top-K：{meta['top_k'] or '未记录'}",
        f"- 相关阈值：{threshold_label}",
        f"- 总体结果：{meta['passed_count']}/{meta['case_count']}（{meta['pass_rate']:.0%}）",
        "",
        "## 分类结果",
        "",
    ]
    if meta["categories"]:
        for category, summary_value in meta["categories"].items():
            summary = _mapping(summary_value)
            lines.append(
                f"- {_markdown_cell(category)}："
                f"{_integer(summary.get('passed_count'))}/"
                f"{_integer(summary.get('case_count'))}"
            )
    else:
        lines.append("暂无分类汇总。")
    lines.extend(
        [
            "",
            "## 逐例结果",
            "",
            "| 结果 | 用例 | 类别 | 查询 | 目标证据 | 目标排名 | 相关候选数 |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for result in meta["results"]:
        expected_ids = result.get("expected_evidence_ids") or []
        expected_target = (
            "、".join(f"E{item}" for item in expected_ids)
            if expected_ids
            else "要求零命中"
        )
        ranks = _mapping(result.get("expected_id_ranks"))
        rank_text = (
            "、".join(
                f"E{key}:{value if value is not None else '未召回'}"
                for key, value in ranks.items()
            )
            or "—"
        )
        values = [
            "通过" if result.get("passed", result.get("hit")) else "未通过",
            result.get("name", ""),
            result.get("category", ""),
            result.get("query", ""),
            expected_target,
            rank_text,
            result.get("relevant_count", 0),
        ]
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
    if not meta["results"]:
        lines.append("| — | 暂无逐例结果 | — | — | — | — | 0 |")
    lines.append("")
    return "\n".join(lines)


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
    evidence_set_id = build_evidence_set_id(evidence_rows)
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
    case_set_id = build_eval_case_set_id(cases)
    report = {
        **report,
        "case_set_id": case_set_id,
        "evidence_set_id": evidence_set_id,
        "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
    }
    run_id = db.create_agent_run(
        int(project_id),
        "retrieval_eval",
        input_data={
            "top_k": top_k,
            "case_set_id": case_set_id,
            "evidence_set_id": evidence_set_id,
            "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
            "relevance_threshold": report["relevance_threshold"],
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
