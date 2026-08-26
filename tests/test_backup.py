"""Project backup and restore tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
from io import BytesIO
from pathlib import Path

from qingji.backup import (
    export_project_backup,
    inspect_project_backup,
    restore_project_backup,
)
from qingji.llm import LLMConfigurationError
from qingji.db import Database
from qingji.projects import create_project_workspace
from qingji.workflow import (
    check_and_store_claim,
    import_text_material,
    review_evidence_card,
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _rewrite_payload(content: bytes, mutate) -> bytes:
    source = zipfile.ZipFile(BytesIO(content), "r")
    files = {item.filename: source.read(item.filename) for item in source.infolist()}
    source.close()
    payload = json.loads(files["project.json"].decode("utf-8"))
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    mutate(payload)
    payload_bytes = _json_bytes(payload)
    files["project.json"] = payload_bytes
    manifest["payload"]["size"] = len(payload_bytes)
    manifest["payload"]["sha256"] = hashlib.sha256(payload_bytes).hexdigest()
    files["manifest.json"] = _json_bytes(manifest)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, value in files.items():
            archive.writestr(path, value)
    return output.getvalue()


def _full_coverage_advice(segments, **_kwargs):
    cards = tuple(
        SimpleNamespace(
            segment_ids=(int(segment["id"]),),
            title="模型片段卡",
            summary="模型根据该脱敏片段生成的可复核摘要。",
            evidence_type="formal_record",
        )
        for segment in segments
    )
    return SimpleNamespace(
        cards=cards,
        discarded_card_count=0,
        as_dict=lambda: {"cards": len(cards), "model": "test-model"},
    )

class ProjectBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "qingji.db")
        self.db.initialize()
        self._model_config_patcher = patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        )
        self._claim_review_patcher = patch(
            "qingji.workflow.request_claim_evidence_review",
            side_effect=LLMConfigurationError("test fallback"),
        )
        self._model_cards_patcher = patch(
            "qingji.workflow.request_evidence_card_generation",
            side_effect=_full_coverage_advice,
        )
        self._model_config_patcher.start()
        self._model_cards_patcher.start()
        self._claim_review_patcher.start()
        self.project_id = create_project_workspace(
            self.db, "备份源项目", "验证完整项目迁移。"
        )
        imported = import_text_material(
            self.db,
            self.project_id,
            "居民表示线上平台步骤较多，工作人员提供了现场指导。",
            source_role="受访居民",
            context="经授权访谈",
            consent_status="confirmed",
            original_filename="访谈记录.txt",
            captured_at=None,
            custom_sensitive_terms=(),
            is_fictional=True,
        )
        self.material_id = imported.material_id
        self.card_id = imported.evidence_card_ids[0]
        card = self.db.get_evidence_card(self.card_id)
        review_evidence_card(
            self.db,
            self.card_id,
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="approved",
            change_reason="已核对授权和脱敏结果。",
        )
        stored = check_and_store_claim(
            self.db, self.project_id, "居民表示线上平台步骤较多。"
        )
        self.claim_id = stored.claim_id
        reviewed_card = self.db.get_evidence_card(self.card_id)
        review_evidence_card(
            self.db,
            self.card_id,
            title=reviewed_card["title"] + "（复核）",
            summary=reviewed_card["summary"],
            evidence_type=reviewed_card["evidence_type"],
            review_status="approved",
            change_reason="复核标题并重新检查既有结论。",
        )
        self.db.create_followup_task(
            self.claim_id,
            "备份恢复任务",
            recommended_action="核对恢复后的完成材料编号。",
            status="done",
            completion_material_id=self.material_id,
        )
        self.db.create_agent_run(
            self.project_id,
            "retrieval_eval",
            claim_id=self.claim_id,
            input_data={
                "cases": [
                    {
                        "name": "恢复编号测试",
                        "expected_evidence_ids": [self.card_id],
                    }
                ]
            },
            output_data={
                "ranked_candidates": [
                    {"evidence_id": self.card_id, "material_id": self.material_id}
                ],
                "expected_id_ranks": {str(self.card_id): 1},
            },
        )

    def tearDown(self) -> None:
        self._claim_review_patcher.stop()
        self._model_cards_patcher.stop()
        self._model_config_patcher.stop()
        self.temp_dir.cleanup()

    def test_round_trip_restores_rows_files_and_remapped_references(self) -> None:
        backup = export_project_backup(self.db, self.project_id)
        inspection = inspect_project_backup(backup.content)

        self.assertTrue(backup.filename.endswith("_v1.zip"))
        self.assertEqual(inspection.source_project_name, "备份源项目")
        self.assertEqual(inspection.counts["materials"], 1)
        self.assertEqual(inspection.counts["evidence_review_events"], 2)
        self.assertEqual(inspection.material_file_count, 2)
        with self.assertRaisesRegex(ValueError, "同名项目"):
            restore_project_backup(self.db, backup.content, "备份源项目")

        restored = restore_project_backup(
            self.db, backup.content, "备份源项目（恢复）"
        )
        self.assertNotEqual(restored.project_id, self.project_id)
        self.assertEqual(restored.restored_files, 2)
        self.assertEqual(
            self.db.get_project_stats(restored.project_id),
            self.db.get_project_stats(self.project_id),
        )
        restored_material = self.db.list_materials(restored.project_id)[0]
        restored_card = self.db.list_evidence_cards(restored.project_id)[0]
        restored_claim = self.db.list_claims(restored.project_id)[0]
        self.assertNotEqual(restored_material["id"], self.material_id)
        self.assertEqual(
            Path(restored_material["raw_path"]).read_text(encoding="utf-8"),
            "居民表示线上平台步骤较多，工作人员提供了现场指导。",
        )
        self.assertTrue(
            (
                Path(self.temp_dir.name)
                / "redacted"
                / f"M{restored_material['id']}_redacted.txt"
            ).is_file()
        )
        history = self.db.list_evidence_review_events(
            restored.project_id, evidence_card_id=int(restored_card["id"])
        )
        self.assertEqual(history[0]["change_reason"], "复核标题并重新检查既有结论。")
        self.assertEqual(history[0]["rechecked_claim_ids"], [restored_claim["id"]])
        restored_run = self.db.list_project_runs(
            restored.project_id, "retrieval_eval"
        )[0]
        self.assertEqual(
            restored_run["input"]["cases"][0]["expected_evidence_ids"],
            [restored_card["id"]],
        )
        self.assertEqual(
            restored_run["output"]["ranked_candidates"][0]["evidence_id"],
            restored_card["id"],
        )
        self.assertEqual(
            restored_run["output"]["ranked_candidates"][0]["material_id"],
            restored_material["id"],
        )
        self.assertEqual(
            restored_run["output"]["expected_id_ranks"],
            {str(restored_card["id"]): 1},
        )
        self.assertEqual(restored_run["claim_id"], restored_claim["id"])
        restored_task = next(
            task
            for task in self.db.list_followup_tasks(project_id=restored.project_id)
            if task["title"] == "备份恢复任务"
        )
        self.assertEqual(
            restored_task["completion_material_id"], restored_material["id"]
        )
        restored_links = self.db.list_claim_evidence_links(restored_claim["id"])
        self.assertTrue(
            all(link["evidence_card_id"] == restored_card["id"] for link in restored_links)
        )
        restored_search = self.db.search_evidence(
            restored.project_id, "线上平台", approved_only=True
        )
        self.assertEqual(restored_search[0]["id"], restored_card["id"])
        self.assertNotEqual(restored_claim["id"], self.claim_id)

    def test_tampered_payload_is_rejected_before_database_write(self) -> None:
        backup = export_project_backup(self.db, self.project_id)
        source = zipfile.ZipFile(BytesIO(backup.content), "r")
        files = {item.filename: source.read(item.filename) for item in source.infolist()}
        source.close()
        files["project.json"] += b" "
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, value in files.items():
                archive.writestr(path, value)

        with self.assertRaisesRegex(ValueError, "哈希校验失败"):
            restore_project_backup(self.db, output.getvalue(), "不应创建")
        self.assertIsNone(self.db.get_project_by_name("不应创建"))

    def test_database_constraint_failure_rolls_back_rows_and_files(self) -> None:
        backup = export_project_backup(self.db, self.project_id)

        def break_evidence_type(payload: dict) -> None:
            payload["tables"]["evidence_cards"][0]["evidence_type"] = "invalid"

        broken = _rewrite_payload(backup.content, break_evidence_type)
        before_raw = set((Path(self.temp_dir.name) / "raw").glob("*"))
        before_redacted = set((Path(self.temp_dir.name) / "redacted").glob("*"))
        with self.assertRaises(sqlite3.IntegrityError):
            restore_project_backup(self.db, broken, "事务回滚项目")
        self.assertIsNone(self.db.get_project_by_name("事务回滚项目"))
        self.assertEqual(before_raw, set((Path(self.temp_dir.name) / "raw").glob("*")))
        self.assertEqual(
            before_redacted,
            set((Path(self.temp_dir.name) / "redacted").glob("*")),
        )

    def test_missing_managed_raw_file_prevents_incomplete_backup(self) -> None:
        raw_path = Path(self.db.get_material(self.material_id)["raw_path"])
        raw_path.unlink()

        with self.assertRaisesRegex(ValueError, "原文文件缺失"):
            export_project_backup(self.db, self.project_id)

    def test_undeclared_or_unsafe_zip_member_is_rejected(self) -> None:
        backup = export_project_backup(self.db, self.project_id)
        output = BytesIO()
        source = zipfile.ZipFile(BytesIO(backup.content), "r")
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in source.infolist():
                archive.writestr(item.filename, source.read(item.filename))
            archive.writestr("../outside.txt", b"unsafe")
        source.close()
        with self.assertRaisesRegex(ValueError, "不安全"):
            inspect_project_backup(output.getvalue())


if __name__ == "__main__":
    unittest.main()
