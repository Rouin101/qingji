"""Reproducible internal benchmark for Qingji's complete text workflow.

All records are fictional and created in an isolated temporary database.  The
benchmark is a development regression set, not evidence from a real fieldwork
project and not an external validity claim.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .claims import evaluate_claim, validate_citation_ids
from .db import Database
from .evidence import is_retrievable_evidence
from .models import Verdict
from .privacy import redact_text
from .retrieval import evidence_candidate_from_mapping, rank_evidence_with_explanations


@dataclass(frozen=True)
class BenchmarkEvidence:
    key: str
    title: str
    quote: str
    summary: str


@dataclass(frozen=True)
class BenchmarkClaim:
    name: str
    text: str
    expected_verdict: Verdict
    target_keys: tuple[str, ...] = ()


_NEUTRAL_EVIDENCE = (
    BenchmarkEvidence("guide", "志愿者步骤指引", "现场志愿者逐步说明办理流程后，一名受访者完成了材料提交。", "志愿者的步骤说明帮助受访者完成提交。"),
    BenchmarkEvidence("checklist", "纸质材料清单", "窗口提供纸质材料清单后，一名受访者按清单备齐了申请材料。", "纸质清单帮助受访者准备材料。"),
    BenchmarkEvidence("reminder", "预约短信提醒", "受访者表示收到预约短信通知后按约定时间到达服务点。", "短信提醒帮助受访者按时到达。"),
    BenchmarkEvidence("large_text", "大字版页面入口", "一名年长受访者打开大字版后更容易看清页面入口。", "大字版改善了页面入口的可读性。"),
    BenchmarkEvidence("bilingual", "双语方向指示", "双语指示牌帮助一名外地访客找到对应办理窗口。", "双语指示帮助访客找到窗口。"),
    BenchmarkEvidence("seating", "等候区座椅体验", "受访者表示等候区增加座椅后，等待时更舒适。", "座椅改善了一名受访者的等候体验。"),
    BenchmarkEvidence("once_notice", "一次告知材料要求", "工作人员一次说明所需材料后，受访者完成了材料准备。", "一次告知帮助受访者完成材料准备。"),
    BenchmarkEvidence("desk", "线下咨询账号绑定", "线下咨询台工作人员解答了受访者的账号绑定问题。", "咨询台处理了账号绑定问题。"),
    BenchmarkEvidence("progress", "办理进度查询入口", "受访者通过进度查询入口看到了当前办理状态。", "进度查询入口展示了办理状态。"),
    BenchmarkEvidence("accessible", "无障碍通道通行", "使用轮椅的访客通过无障碍通道进入了服务大厅。", "无障碍通道支持轮椅访客进入大厅。"),
)

_CONFLICT_EVIDENCE = (
    BenchmarkEvidence("login_hard", "登录验证码需要帮助", "受访者第一次登录线上申请平台时找不到验证码，需要工作人员帮助。", "首次登录时遇到验证码操作困难。"),
    BenchmarkEvidence("login_smooth", "登录验证码操作顺利", "另一名受访者熟悉线上申请平台，独立完成验证码登录且没有遇到困难。", "熟悉平台的受访者独立完成登录。"),
    BenchmarkEvidence("terminal_hard", "自助终端菜单难找", "受访者使用自助终端时不会操作菜单，需要志愿者帮助。", "自助终端菜单给一名受访者带来使用困难。"),
    BenchmarkEvidence("terminal_smooth", "自助终端办理顺利", "另一名受访者在自助终端上操作顺利，独立完成了办理。", "受访者独立完成自助终端办理。"),
    BenchmarkEvidence("scan_hard", "扫码登记遇到问题", "一名受访者扫码登记时遇到问题，寻求现场人员帮助。", "扫码登记过程中有人需要帮助。"),
    BenchmarkEvidence("scan_smooth", "扫码登记操作顺畅", "另一名受访者扫码登记操作顺畅，没有遇到问题。", "扫码登记也存在顺利完成的体验。"),
    BenchmarkEvidence("payment_hard", "线上缴费页面跳转困难", "受访者在线上缴费页面跳转时遇到困难，未能独立完成。", "线上缴费页面跳转给受访者带来困难。"),
    BenchmarkEvidence("payment_smooth", "线上缴费独立完成", "另一名受访者线上缴费使用顺利，独立完成支付。", "线上缴费也有顺利完成的体验。"),
    BenchmarkEvidence("upload_hard", "电子表单附件上传困难", "受访者填写电子表单时不会上传附件，需要工作人员帮助。", "附件上传步骤给受访者带来困难。"),
    BenchmarkEvidence("upload_smooth", "电子表单附件上传顺利", "另一名受访者独立上传电子表单附件，操作顺利。", "附件上传也有独立完成的体验。"),
)

BENCHMARK_EVIDENCE = _NEUTRAL_EVIDENCE + _CONFLICT_EVIDENCE

_SUPPORTED = (
    ("S01", "志愿者的流程讲解帮助一名受访者交齐材料。", "guide"),
    ("S02", "纸质清单帮助一名受访者备齐申请材料。", "checklist"),
    ("S03", "预约通知帮助一名受访者准时到达服务点。", "reminder"),
    ("S04", "大号字体让一名年长受访者更容易看清入口。", "large_text"),
    ("S05", "双语路标帮助一名外地访客找到办事窗口。", "bilingual"),
    ("S06", "等候座位改善了一名受访者等待时的感受。", "seating"),
    ("S07", "工作人员一次说明帮助受访者准备所需材料。", "once_notice"),
    ("S08", "现场咨询人员解决了一名受访者的账户绑定疑问。", "desk"),
    ("S09", "状态查询功能让一名受访者看到办理进展。", "progress"),
    ("S10", "无障碍入口方便轮椅访客进入服务大厅。", "accessible"),
)

_UNSUPPORTED_TEXTS = (
    "校园食堂夜间窗口增加了面食种类。",
    "宿舍空调维修平均需要三个工作日。",
    "图书馆周末延长了自习室开放时间。",
    "校车在雨天调整了发车间隔。",
    "社区公园新栽种了二十棵树。",
    "运动场照明在晚上十点关闭。",
    "快递站使用了新的货架编号方式。",
    "食堂餐具回收区域进行了重新布置。",
    "校园超市增加了文具销售区域。",
    "宿舍楼完成了屋顶防水施工。",
)

_CONFLICT_QUERIES = (
    ("C01", "线上申请平台登录时需要帮助。", ("login_hard", "login_smooth")),
    ("C02", "线上申请的验证码登录存在使用困难。", ("login_hard", "login_smooth")),
    ("C03", "自助终端菜单不会操作，需要人工帮助。", ("terminal_hard", "terminal_smooth")),
    ("C04", "自助设备办理时遇到操作困难。", ("terminal_hard", "terminal_smooth")),
    ("C05", "扫码登记过程中需要现场人员帮助。", ("scan_hard", "scan_smooth")),
    ("C06", "二维码登记操作存在困难。", ("scan_hard", "scan_smooth")),
    ("C07", "线上缴费页面跳转时遇到困难。", ("payment_hard", "payment_smooth")),
    ("C08", "网络支付流程不好用，难以独立完成。", ("payment_hard", "payment_smooth")),
    ("C09", "电子表单上传附件时需要工作人员帮助。", ("upload_hard", "upload_smooth")),
    ("C10", "在线表格的文件上传步骤不会操作。", ("upload_hard", "upload_smooth")),
)

BENCHMARK_CLAIMS = tuple(
    BenchmarkClaim(name, text, Verdict.SUPPORTED, (target,))
    for name, text, target in _SUPPORTED
) + tuple(
    BenchmarkClaim(
        f"P{index:02d}",
        f"受访者普遍认为{text.rstrip('。')}",
        Verdict.PARTIALLY_SUPPORTED,
        (target,),
    )
    for index, (_, text, target) in enumerate(_SUPPORTED, start=1)
) + tuple(
    BenchmarkClaim(f"U{index:02d}", text, Verdict.UNSUPPORTED)
    for index, text in enumerate(_UNSUPPORTED_TEXTS, start=1)
) + tuple(
    BenchmarkClaim(name, text, Verdict.CONTRADICTED, targets)
    for name, text, targets in _CONFLICT_QUERIES
)


def _macro_f1(expected: list[str], actual: list[str]) -> tuple[float, dict[str, float]]:
    labels = [item.value for item in Verdict]
    per_label: dict[str, float] = {}
    for label in labels:
        true_positive = sum(e == label and a == label for e, a in zip(expected, actual))
        false_positive = sum(e != label and a == label for e, a in zip(expected, actual))
        false_negative = sum(e == label and a != label for e, a in zip(expected, actual))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        per_label[label] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return sum(per_label.values()) / len(per_label), per_label


def _pii_report() -> dict[str, Any]:
    samples: list[tuple[str, list[str]]] = []
    samples.extend((f"联系电话 1380000{index:04d}", []) for index in range(10))
    samples.extend((f"身份证 32010119900101{index:04d}", []) for index in range(10))
    samples.extend((f"邮箱 user{index}@example.org", []) for index in range(10))
    samples.extend((f"访谈地点为青迹测试地址{index}号", [f"青迹测试地址{index}号"]) for index in range(20))
    detected = 0
    by_kind: Counter[str] = Counter()
    for text, custom_terms in samples:
        result = redact_text(text, custom_terms=custom_terms)
        if result.spans:
            detected += 1
            by_kind.update(span.kind for span in result.spans)
    return {
        "case_count": len(samples),
        "detected_count": detected,
        "recall": detected / len(samples),
        "detected_by_kind": dict(by_kind),
    }


def run_formal_project_benchmark() -> dict[str, Any]:
    """Run the 20-material/40-claim benchmark in an isolated database."""

    with TemporaryDirectory(prefix="qingji_benchmark_") as temp_dir:
        db = Database(Path(temp_dir) / "benchmark.db")
        db.initialize()
        project_id = db.create_project("青迹正式内部评测集", "全部材料均为模拟数据")
        evidence_ids: dict[str, int] = {}
        for index, item in enumerate(BENCHMARK_EVIDENCE, start=1):
            material_id = db.create_material(
                project_id,
                "text",
                original_filename=f"模拟材料_{index:02d}.txt",
                source_role="模拟受访者",
                context="内部开发评测，不代表真实调研",
                consent_status="confirmed",
                processing_status="ready",
                is_fictional=True,
            )
            segment_id = db.create_segment(material_id, 1, item.quote, locator="模拟片段 1")
            evidence_ids[item.key] = db.create_evidence_card(
                project_id,
                segment_id,
                "interview_statement",
                item.title,
                item.quote,
                item.summary,
                source_locator="模拟片段 1",
                review_status="approved",
            )

        rows = [row for row in db.list_evidence_cards(project_id) if is_retrievable_evidence(row)]
        candidates = [evidence_candidate_from_mapping(row) for row in rows]
        expected: list[str] = []
        actual: list[str] = []
        results: list[dict[str, Any]] = []
        retrieval_hits = 0
        citation_valid_count = 0
        overclaim_hits = 0
        for case in BENCHMARK_CLAIMS:
            evaluation = evaluate_claim(case.text, candidates)
            expected.append(case.expected_verdict.value)
            actual.append(evaluation.verdict.value)
            target_ids = [evidence_ids[key] for key in case.target_keys]
            all_matches = rank_evidence_with_explanations(
                case.text, candidates, limit=len(candidates)
            )
            matches = all_matches[:5]
            relevant_ids = [int(match.candidate.id) for match in matches if match.score >= 0.08]
            relevant_scores = [
                round(float(match.score), 4)
                for match in matches
                if match.score >= 0.08
            ]
            retrieval_passed = not target_ids or all(item in relevant_ids for item in target_ids)
            retrieval_hits += int(retrieval_passed)
            citation_valid = validate_citation_ids(evaluation, {item.id for item in candidates})
            citation_valid_count += int(citation_valid)
            if case.expected_verdict == Verdict.PARTIALLY_SUPPORTED:
                overclaim_hits += int(evaluation.verdict == Verdict.PARTIALLY_SUPPORTED)
            results.append(
                {
                    "name": case.name,
                    "claim_text": case.text,
                    "expected_verdict": case.expected_verdict.value,
                    "actual_verdict": evaluation.verdict.value,
                    "target_evidence_ids": target_ids,
                    "target_scores": {
                        str(target_id): next(
                            (
                                round(float(match.score), 4)
                                for match in all_matches
                                if int(match.candidate.id) == target_id
                            ),
                            0.0,
                        )
                        for target_id in target_ids
                    },
                    "retrieved_evidence_ids": relevant_ids,
                    "retrieved_scores": relevant_scores,
                    "retrieval_passed": retrieval_passed,
                    "citation_valid": citation_valid,
                    "passed": evaluation.verdict == case.expected_verdict,
                }
            )

        macro_f1, per_verdict_f1 = _macro_f1(expected, actual)
        verdict_correct = sum(e == a for e, a in zip(expected, actual))
        return {
            "dataset": "qingji_formal_internal_v1",
            "fictional": True,
            "material_count": len(BENCHMARK_EVIDENCE),
            "claim_count": len(BENCHMARK_CLAIMS),
            "verdict_distribution": dict(Counter(expected)),
            "verdict_accuracy": verdict_correct / len(expected),
            "verdict_macro_f1": macro_f1,
            "per_verdict_f1": per_verdict_f1,
            "retrieval_recall_at_5": retrieval_hits / len(BENCHMARK_CLAIMS),
            "citation_validity": citation_valid_count / len(BENCHMARK_CLAIMS),
            "overclaim_recall": overclaim_hits / 10,
            "pii": _pii_report(),
            "passed_count": verdict_correct,
            "results": results,
        }
