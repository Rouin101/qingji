# 青迹数据字典

## 架构版本

当前 SQLite 架构版本为 2。`PRAGMA user_version` 保存机器可读版本，`schema_migrations` 保存已经登记的版本、名称和应用时间。

## 核心实体

| 表 | 关键字段 | 含义与关系 |
| --- | --- | --- |
| `projects` | `name`、`description`、`term_pairs_json`、`archived_at` | 项目边界；术语映射只作用于本项目 |
| `materials` | `project_id`、`raw_path`、`source_role`、`context`、`consent_status`、`is_fictional` | 一份来源材料及其授权、场景和模拟标识 |
| `segments` | `material_id`、`sequence_no`、`redacted_text`、`locator`、`pii_flags_json` | 材料的脱敏片段与原文位置 |
| `evidence_cards` | `project_id`、`segment_id`、`evidence_type`、`quote`、`summary`、`review_status` | 可审核证据单元；引用资格由授权与审核状态共同决定 |
| `evidence_review_events` | `evidence_card_id`、`before_json`、`after_json`、`change_reason`、`reviewer`、`rechecked_claim_ids_json` | 追加式审核历史；`reviewer` 是自填文本，不代表已认证身份 |
| `claims` | `project_id`、`claim_text`、`verdict`、`reason`、`safe_rewrite`、`rule_flags_json` | 待写入报告的表述及当前四级核验结果 |
| `claim_evidence_links` | `claim_id`、`evidence_card_id`、`relation`、`rationale` | 结论与证据的支持、冲突或背景关系 |
| `claim_candidates` | `project_id`、`material_id`、`claim_text`、`source_segment_ids_json`、`status` | 从材料提取、等待人工选择的结论候选 |
| `followup_tasks` | `claim_id`、`recommended_action`、`status`、`completion_material_id` | 由证据缺口形成的补证任务 |
| `agent_runs` | `project_id`、`claim_id`、`run_type`、`status`、`input_json`、`output_json`、`error_message` | 模型和评测运行记录，用于失败恢复与诊断 |
| `pilot_sessions` | `project_id`、`session_code`、`session_date`、两类耗时、提醒采纳、误报漏报、困惑点和下一步动作 | 项目内真实试用会话；只记录人工确认的过程指标，不代表现实真伪判断 |
| `schema_migrations` | `version`、`name`、`applied_at` | 数据库架构版本登记 |

## 状态口径

- 授权：`unknown`、`confirmed`、`denied`。
- 证据审核：`draft`、`approved`、`rejected`。
- 结论：`supported`、`partially_supported`、`unsupported`、`contradicted`。
- 补证任务：`open`、`done`、`cancelled`。
- 真实试用：`planned`、`in_progress`、`completed`、`paused`。

## 文件数据

- `data/raw/` 保存托管原文。
- `data/redacted/` 保存脱敏文本。
- `data/*.db` 保存本地数据库。
- `output/` 保存本地生成的报告和备份。

这些路径中的实际内容均不进入 Git。项目 ZIP 可能包含原文，应按敏感资料保管。
