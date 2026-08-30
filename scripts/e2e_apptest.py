"""End-to-end UI verification driven through Streamlit's AppTest.

Runs the real multi-page app against a throwaway data directory and walks the
full vertical slice the way a presenter would:

    1. import an authorized text material (with a phone number + custom term)
    2. approve the generated evidence card
    3. check the group-generalization claim on page 2
    4. add the opposite-viewpoint material
    5. re-check the same claim
    6. export the Markdown and assert it stays traceable
    7. back up and restore the complete project under a new name

Every step asserts the page ran without exceptions and then verifies the
underlying database state directly.
"""

from __future__ import annotations

from datetime import date
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_DATA_DIR = tempfile.mkdtemp(prefix="qingji_e2e_")
os.environ["QINGJI_DATA_DIR"] = _DATA_DIR

from streamlit.testing.v1 import AppTest  # noqa: E402

from qingji.backup import (  # noqa: E402
    export_project_backup,
    inspect_project_backup,
    restore_project_backup,
)
from qingji.db import Database  # noqa: E402
from qingji.export import export_project_markdown  # noqa: E402
from qingji.llm import (  # noqa: E402
    EvidenceCardGenerationAdvice,
    EvidenceCardGenerationItem,
    LLMError,
    MaterialClaimCandidateAdvice,
)

IMPORT_TEXT = (
    "受访者甲说：我第一次使用线上便民平台时，不知道验证码填在哪里，"
    "后来在志愿者的帮助下完成了申请。手机13812345678。"
)
GROUP_CLAIM = "当地居民普遍认为线上办事平台使用困难。"
MATERIAL_FILENAME = "材料_新访谈_已授权.txt"


def _offline_card_generation(segments, *, max_cards: int, **_kwargs):
    return EvidenceCardGenerationAdvice(
        cards=tuple(
            EvidenceCardGenerationItem(
                segment_ids=(int(segment["id"]),),
                title="首次使用线上平台时需要协助",
                summary="一名受访者首次使用线上平台时需要志愿者帮助。",
                evidence_type="interview_statement",
                uncertainties=(),
            )
            for segment in segments[:max_cards]
        ),
        uncertainties=(),
        model="offline-e2e-model",
        chunk_count=1,
    )


def _expect_no_exception(app: AppTest, step: str) -> None:
    assert not app.exception, f"{step}: 页面异常 {app.exception}"


def _success_texts(app: AppTest) -> list[str]:
    return [str(item.value) for item in app.success]


def _db() -> Database:
    database = Database(Path(_DATA_DIR) / "qingji.db")
    database.initialize()
    return database


def _approved_card_count() -> int:
    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    if project is None:
        return 0
    return len(
        database.list_evidence_cards(
            int(project["id"]), review_status="approved"
        )
    )


def _draft_card_ids() -> list[int]:
    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    assert project is not None
    drafts = database.list_evidence_cards(
        int(project["id"]), review_status="draft"
    )
    assert drafts, "导入后应生成待审核证据卡"
    return [int(item["id"]) for item in drafts]


def step_import_and_approve(app: AppTest) -> None:
    app.switch_page("pages/1_材料与证据.py")
    app.run()
    _expect_no_exception(app, "进入材料页")

    app.text_area[0].set_value(IMPORT_TEXT)
    app.text_input[0].set_value(MATERIAL_FILENAME)
    app.selectbox[0].select("受访者")
    app.text_input[1].set_value("线上便民服务体验访谈")
    app.text_input[2].set_value("受访者甲")
    app.radio[0].set_value("confirmed")
    app.date_input[0].set_value(date(2026, 8, 25))
    app.checkbox[0].set_value(True)
    app.button[0].click()
    app.run()
    _expect_no_exception(app, "导入材料")
    assert any("已保存" in text for text in _success_texts(app)), _success_texts(app)

    card_ids = _draft_card_ids()
    for card_id in card_ids:
        app.radio(key=f"decision_{card_id}").set_value("approved")
        app.text_area(key=f"review_reason_{card_id}").set_value(
            "已核对材料来源与授权。"
        )
        app.button(
            key=f"FormSubmitter:evidence_edit_{card_id}-保存审核结果"
        ).click()
        app.run()
        _expect_no_exception(app, f"批准证据卡 E{card_id}")
    assert _approved_card_count() == 3 + len(card_ids), "全部新卡应完成人工批准"
    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    for card_id in card_ids:
        events = database.list_evidence_review_events(
            int(project["id"]), evidence_card_id=card_id
        )
        assert len(events) == 1, "每张人工批准卡应生成一条审核历史"
        assert events[0]["change_reason"].startswith("已核对材料")


def step_check_claim(app: AppTest) -> None:
    app.switch_page("pages/2_结论核验.py")
    app.run()
    _expect_no_exception(app, "进入核验页")

    app.text_area[0].set_value(GROUP_CLAIM)
    app.button[0].click()
    app.run()
    _expect_no_exception(app, "核验结论")
    assert any("核验完成" in text for text in _success_texts(app)), _success_texts(app)

    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    claims = database.list_claims(int(project["id"]))
    claim = next(
        (item for item in claims if item["claim_text"] == GROUP_CLAIM), None
    )
    assert claim is not None, "核验后应存在待核验结论"
    assert claim["verdict"] == "partially_supported", claim["verdict"]
    tasks = database.list_followup_tasks(claim_id=int(claim["id"]))
    assert any(task["status"] == "open" for task in tasks), "部分支持应创建补证任务"


def step_supplement_and_recheck(app: AppTest) -> None:
    database = _db()
    project = database.get_project_by_name("数字便民服务体验调研")
    claim = next(
        item
        for item in database.list_claims(int(project["id"]))
        if item["claim_text"] == GROUP_CLAIM
    )
    app.button(
        key=f"add_demo_supplement_{project['id']}_{claim['id']}"
    ).click()
    app.run()
    _expect_no_exception(app, "加入补充材料")
    assert any("已加入" in text for text in _success_texts(app)), _success_texts(app)

    app.button(
        key=f"recheck_claim_{project['id']}_{claim['id']}"
    ).click()
    app.run()
    app.run()  # the handler calls st.rerun(), settle one extra pass
    _expect_no_exception(app, "重新核验")

    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    claims = database.list_claims(int(project["id"]))
    claim = next(
        (item for item in claims if item["claim_text"] == GROUP_CLAIM), None
    )
    assert claim is not None
    assert claim["verdict"] == "contradicted", claim["verdict"]
    relations = {
        link["relation"]
        for link in database.list_claim_evidence_links(int(claim["id"]))
    }
    assert "contradict" in relations, "补充相反观点后应出现冲突证据"


def step_export(app: AppTest) -> None:
    app.switch_page("pages/3_成果与缺口.py")
    app.run()
    _expect_no_exception(app, "进入成果页")

    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    markdown = export_project_markdown(database, int(project["id"]))
    assert GROUP_CLAIM in markdown
    assert "存在冲突" in markdown
    assert "证据目录" in markdown
    assert "证据审核变更日志" in markdown
    assert "已核对材料来源与授权。" in markdown
    assert "13812345678" not in markdown, "导出不得包含脱敏前手机号"
    print("导出 Markdown 长度：", len(markdown))


def step_backup_and_restore() -> None:
    database = _db()
    project = database.get_project_by_name(
        "数字便民服务体验调研"
    )
    source_id = int(project["id"])
    backup = export_project_backup(database, source_id)
    inspection = inspect_project_backup(backup.content)
    assert inspection.counts["materials"] >= 4
    restored = restore_project_backup(
        database, backup.content, "端到端备份恢复副本"
    )
    assert database.get_project_stats(restored.project_id) == database.get_project_stats(
        source_id
    )
    restored_markdown = export_project_markdown(database, restored.project_id)
    assert GROUP_CLAIM in restored_markdown
    assert "证据审核变更日志" in restored_markdown
    assert "13812345678" not in restored_markdown


def main() -> None:
    app = AppTest.from_file("app.py", default_timeout=60)
    app.run()
    _expect_no_exception(app, "启动应用")
    print("数据库目录：", _DATA_DIR)

    configured = SimpleNamespace(
        configured=True,
        model="offline-e2e-model",
        provider="offline-test",
        max_context_chars=12000,
    )
    with patch("qingji.workflow.llm_settings", configured), patch(
        "qingji.workflow.request_evidence_card_generation",
        side_effect=_offline_card_generation,
    ), patch(
        "qingji.workflow.request_material_claim_candidates",
        return_value=MaterialClaimCandidateAdvice(
            candidates=(), uncertainties=(), model="offline-e2e-model"
        ),
    ), patch(
        "qingji.workflow.request_claim_evidence_review",
        side_effect=LLMError("E2E 使用本地规则，不调用外部语义复核"),
    ):
        step_import_and_approve(app)
    print("[OK] 材料导入与证据批准通过")
    with patch(
        "qingji.workflow.llm_settings", SimpleNamespace(configured=False)
    ):
        step_check_claim(app)
        print("[OK] 结论核验（部分支持 + 补证任务）通过")
        step_supplement_and_recheck(app)
    print("[OK] 补充观点与重新核验（存在冲突）通过")
    step_export(app)
    print("[OK] Markdown 可信导出通过")
    step_backup_and_restore()
    print("[OK] 项目完整备份与恢复通过")
    print("E2E 全部通过")


if __name__ == "__main__":
    main()
