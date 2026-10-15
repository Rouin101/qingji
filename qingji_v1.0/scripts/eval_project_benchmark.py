"""Run Qingji's formal fictional internal benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qingji.project_benchmark import run_formal_project_benchmark


def main() -> int:
    report = run_formal_project_benchmark()
    print("Qingji formal internal benchmark (fictional data)")
    print(f"Materials: {report['material_count']}")
    print(f"Claims: {report['claim_count']}")
    print(f"Verdict accuracy: {report['verdict_accuracy']:.1%}")
    print(f"Verdict Macro-F1: {report['verdict_macro_f1']:.3f}")
    print(f"Retrieval Recall@5: {report['retrieval_recall_at_5']:.1%}")
    print(f"Overclaim recall: {report['overclaim_recall']:.1%}")
    print(f"PII recall: {report['pii']['recall']:.1%}")
    print(f"Citation validity: {report['citation_validity']:.1%}")
    failures = [item for item in report["results"] if not item["passed"] or not item["retrieval_passed"]]
    if failures:
        print("Failures:")
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    targets = (
        report["verdict_macro_f1"] >= 0.80
        and report["retrieval_recall_at_5"] >= 0.90
        and report["overclaim_recall"] >= 0.90
        and report["pii"]["recall"] >= 0.95
        and report["citation_validity"] == 1.0
    )
    return 0 if targets else 1


if __name__ == "__main__":
    raise SystemExit(main())
