"""Run Qingji's fixed retrieval regression set on isolated demo data."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DATA_DIR = tempfile.mkdtemp(prefix="qingji_retrieval_eval_")
os.environ["QINGJI_DATA_DIR"] = _DATA_DIR

from qingji.db import Database  # noqa: E402
from qingji.demo import create_demo_project  # noqa: E402
from qingji.retrieval_eval import evaluate_retrieval  # noqa: E402


def main() -> int:
    database = Database(Path(_DATA_DIR) / "qingji.db")
    database.initialize()
    project_id = create_demo_project(database)
    report = evaluate_retrieval(database, project_id, top_k=3)
    for index, result in enumerate(report["results"], start=1):
        status = "OK" if result["hit"] else "MISS"
        rank = result["hit_rank"] if result["hit_rank"] is not None else "none"
        print(f"[{status}] case_{index} | rank={rank}")
    print(
        f"Hit@{report['top_k']}: {report['hit_count']}/"
        f"{report['case_count']} ({report['hit_rate']:.0%})"
    )
    return 0 if report["hit_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
