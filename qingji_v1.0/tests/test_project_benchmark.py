from __future__ import annotations

import unittest

from qingji.project_benchmark import run_formal_project_benchmark


class FormalProjectBenchmarkTests(unittest.TestCase):
    def test_fictional_benchmark_meets_frozen_internal_targets(self) -> None:
        report = run_formal_project_benchmark()

        self.assertTrue(report["fictional"])
        self.assertEqual(report["material_count"], 20)
        self.assertEqual(report["claim_count"], 40)
        self.assertEqual(set(report["verdict_distribution"].values()), {10})
        self.assertGreaterEqual(report["verdict_macro_f1"], 0.80)
        self.assertGreaterEqual(report["retrieval_recall_at_5"], 0.90)
        self.assertGreaterEqual(report["overclaim_recall"], 0.90)
        self.assertGreaterEqual(report["pii"]["recall"], 0.95)
        self.assertEqual(report["citation_validity"], 1.0)


if __name__ == "__main__":
    unittest.main()
