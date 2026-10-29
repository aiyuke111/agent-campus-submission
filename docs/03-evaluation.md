# 03 评估

## 测试环境与命令

- Python 3.10，Windows
- 运行时零第三方依赖；测试使用 `pytest 9.2`
- 命令：`pytest -q`

```
$ pytest -q
..................................................................       [100%]
66 passed
```

完整测试输出保存在 `examples/test-report.txt`（`66 passed`），供评审直接查看。

| 测试文件 | 数量 | 覆盖内容 |
|---|---|---|
| `tests/test_tools.py` | 9 | 素材不存在、必填字段缺失、风险规则、时段冲突、幂等保存、保存失败、幂等键 |
| `tests/test_guards.py` | 7 | 发布动作拦截、未知动作、硬性要求标记、前置条件（缺素材/缺规则/参数篡改） |
| `tests/test_acceptance.py` | 7 | 6 个验收点 + 重复提交只生成一份草稿 |
| `tests/test_paths.py` | 6 | 动作序列、两条路径、Trace 字段、无发布动作 |
| `tests/test_limits.py` | 2 | 步数上限、工具调用上限 |
| `tests/test_cli.py` | 7 | CLI 正常/批量、BOM、非法 JSON、文件缺失、空 material_id、未知素材 |
| `tests/test_hardening.py` | 28 | 反例：虚报完成、跳过审核、草稿撞时段、真实 I/O 失败、非法输入、模型异常、真实模型适配器、抢占重试、重复动作、review 归一化 |

## 验收点实测

| 验收点 | 输入 | 实际结果 | 关键字段 | Trace |
|---|---|---|---|---|
| 正常排期 | `request_M05_normal` | 草稿待确认 | `NEEDS_CONFIRMATION`，`suggested_slot=20:00`，`draft.saved=true`，`published=false` | `request_M05_normal.trace.json` |
| 素材信息缺失 | `request_M02_missing` | 请求补充 | `NEEDS_INPUT`，`draft.saved=false` | `request_M02_missing.trace.json` |
| 规则风险 | `request_M03_risk` | 阻断 | `RISK_BLOCKED`，未查时段、未保存 | `request_M03_risk.trace.json` |
| 时段冲突 | `request_M01_conflict` | 建议 19:00 替代 | `alternative=true`，`hard_requirement_modified=false`，原要求 18:00 保留 | `request_M01_conflict.trace.json` |
| 重复提交 | 同一请求再跑一次 | 返回同一草稿 | `duplicate=true`，`draft_id` 相同；`drafts.json` 中 M01 仅 1 条 | `request_M01_duplicate.second.trace.json` |
| 保存失败 | `--inject save_fail` | 明确失败 | `SAVE_FAILED`，`draft.saved=false`，带错误码 | `request_M05_normal.savefail.trace.json` |
| 步数上限 | `--max-steps 2` | 未完成 | `INCOMPLETE`，保留 `collected.material` | `request_M01_conflict.limit.trace.json` |

## 评审问题与修复对照

| # | 评审指出的问题 | 修复 | 验证 |
|---|---|---|---|
| 1 | 模型结束结论可虚报"已保存" | Agent 用真实证据复核 `finish`；不一致强制 `ERROR`，记录 `claim_violations` | `test_finish_cannot_claim_saved_without_draft`、`test_finish_cannot_claim_pass_without_rules`、`test_finish_cannot_claim_save_failed_when_saved` |
| 2 | 模型可跳过审核直接保存 | `guards.check_preconditions` 强制前置步骤与参数一致性 | `test_save_before_audit_is_rejected`、`test_high_risk_material_cannot_be_saved`、`test_precondition_*` |
| 3 | 不同素材可占用同一时段 | 查询把其他素材草稿计为占用；保存时锁内二次检查并抛 `SLOT_TAKEN` | `test_save_rejects_slot_taken_by_other_material`、`test_query_sees_saved_drafts`、`test_agent_avoids_slot_taken_by_other_draft` |
| 4 | 真实写盘失败崩溃、内存被污染 | 临时文件 + `os.replace` 原子写；`OSError` 转 `SAVE_FAILED`；写成功后才更新内存 | `test_atomic_write_failure_is_tool_error`、`test_agent_real_io_failure_returns_save_failed` |
| 5 | 非法日期崩溃、非法时间误报 `NO_SLOT`、`hard:"false"` 被当 true | 请求层校验日期/时间/布尔类型，非法输入返回 `NEEDS_INPUT` | `test_invalid_request_returns_needs_input`（4 组）、`test_hard_string_false_is_parsed` |
| 6 | 模型输出异常导致 traceback | 决策/执行/CLI 三层兜底，统一转 `ERROR` | `test_policy_exception_is_structured`、`test_policy_non_dict_output_is_structured`、`test_publish_action_is_rejected`、CLI 兜底 |
| 7 | 幂等键未包含请求意图 | 键加入 `requested_time` 与 `hard` | `test_idempotency_key_includes_requested_intent` |
| 8 | `search_days` 配置不生效 | CLI 从 `data/slots.json` 注入策略 | `test_policy_uses_search_days_from_config` |
| 9 | 只支持单素材请求 | CLI 支持重复 `--request` 批量处理 | `test_cli_batch_runs_multiple_requests` |
| 10 | 真实模型适配器未测试 | 注入 fake client 覆盖正常/坏 JSON/空响应/未知动作/网络异常 | `test_openai_policy_*`（5 条） |
| 11 | 默认 Mock 是固定分支 | 保留 Mock 作为离线基线；CLI 接通 `--policy openai`，动作协议与决策循环不变；Mock 边界如实标注 | 见 `docs/02` 与 `docs/04` |

## 真实模型运行记录（DeepSeek）

评测环境提供了可用的 DeepSeek Key（不写入仓库），使用 `--policy openai` 实际跑通 3 条路径：

| 路径 | 输入 | 结果 | 步数/工具 | Trace |
|---|---|---|---|---|
| 正常 | `request_M05_normal` | `NEEDS_CONFIRMATION`，20:00 草稿，`PASS` | 5 / 4 | `examples/traces/openai/openai_normal.trace.json` |
| 冲突 | `request_M01_conflict` | `NEEDS_CONFIRMATION`，18:00 占用→模型保存 19:00，`PASS` | 5 / 4 | `examples/traces/openai/openai_conflict.trace.json` |
| 风险 | `request_M03_risk` | `BLOCKED` / `RISK_BLOCKED`，未查询时段、未保存 | 3 / 2 | `examples/traces/openai/openai_risk.trace.json` |

Trace 中每步的 `decision_basis` 为模型生成（如「18:00 已被占用，改存可用候选 19:00 草稿」），动作随工具观察结果变化，可复核模型驱动的决策循环。  
模型返回过非标准 `review_status=PENDING_CONFIRMATION`，Agent 归一化为 `PASS` 并记录在 `normalized` 字段，避免污染状态机。

复现命令（仓库不保存 Key）：

```bash
export OPENAI_API_KEY=<key>
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_MODEL=deepseek-chat
python scripts/run_openai_examples.py
```

## 两条执行路径（Trace 对照）

**正常路径**（`request_M05_normal.trace.json`）：

```
get_material → check_rules → query_slots(2026-11-05, 20:00) → save_draft(20:00) → finish
```

**冲突调整路径**（`request_M01_conflict.trace.json`）：

```
get_material → check_rules → query_slots(2026-11-05, 18:00)
            → 观察到 18:00 占用、候选 19:00
            → save_draft(19:00) → finish（替代时段待确认）
```

**阻断路径**（`request_M03_risk.trace.json`）：

```
get_material → check_rules → 命中 R01（版权 high）→ finish（RISK_BLOCKED）
```

## 健壮性与输入异常

| 场景 | 期望 | 实测 |
|---|---|---|
| BOM JSON 请求 | 正常解析 | `exit=0`，正常业务结果 |
| 非法 JSON / 文件不存在 | 结构化错误 | `exit=2`，`status=ERROR`，无 traceback |
| 空 `material_id` | 请求补充 | `exit=0`，`NEEDS_INPUT` |
| 非法日期 `2026-13-40` | `NEEDS_INPUT` | `exit=0`，不崩溃 |
| 非法时间 `25:99` | `NEEDS_INPUT` | 不再误报 `NO_SLOT` |
| `hard="false"` | 解析为软要求 | `requested_slot.hard=false` |
| 素材不存在 M99 | 请求补充 | `NEEDS_INPUT` |
| 日期无排期数据 | 窗口内无时段 | `NO_SLOT` |

## 复测记录

- `pytest -q` 连续运行 3 次，均为 `66 passed`；
- 仓库复制到独立临时目录（不含 `.git`）后重新执行 `pytest` 与 `scripts/run_examples.py`，结果一致；
- 示例不变量：`drafts.json` 2 条（M01 19:00、M05 20:00）、重复提交同 `draft_id`、无跨素材同时段、无发布状态；
- 代码与测试中无绝对路径依赖。

## 未覆盖与限制

- 真实模型只验证了 DeepSeek `deepseek-chat` 一个模型，其他模型/温度下的决策稳定性未覆盖；
- 工具失败覆盖两类：注入式 `save_fail`（示例场景）与真实 `OSError` 原子写失败（单元测试）；未接真实网络工具；
- 文件锁 + 原子写只做了单机防护，未做多进程压力测试；
- 规则引擎为示例级，未抽象通用 DSL；
- 未接入真实发布系统（按题意仅保存草稿）。
