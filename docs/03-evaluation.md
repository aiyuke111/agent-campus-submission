# 03 评估

## 测试环境

- Python 3.10，Windows
- 运行时零第三方依赖；测试使用 `pytest 9.2`
- 命令：`pytest -q`

## 测试结果

```
$ pytest -q
..................................                                       [100%]
34 passed
```

| 测试文件 | 数量 | 覆盖内容 |
|---|---|---|
| `tests/test_tools.py` | 9 | 素材不存在、必填字段缺失、高风险/中风险规则、时段冲突与候选、整日无候选、幂等保存、保存失败、幂等键稳定性 |
| `tests/test_guards.py` | 4 | 发布类动作拦截、未知动作拦截、硬性要求变更标记、工具层无发布能力 |
| `tests/test_acceptance.py` | 7 | 6 个验收点 + 重复提交只生成一份草稿 |
| `tests/test_paths.py` | 6 | 两条执行路径、动作序列、Trace 字段、无发布动作 |
| `tests/test_limits.py` | 2 | 步数上限、工具调用上限 |
| `tests/test_cli.py` | 6 | CLI 正常路径、BOM 兼容、非法 JSON、文件缺失、空 material_id、未知素材 |

## 验收点实测

| 验收点 | 输入 | 实际结果 | 关键字段 | Trace |
|---|---|---|---|---|
| 正常排期 | `request_M05_normal` | 通过，草稿待确认 | `status=NEEDS_CONFIRMATION`，`suggested_slot=20:00`，`draft.saved=true`，`published=false` | `request_M05_normal.trace.json` |
| 素材信息缺失 | `request_M02_missing` | 请求补充，未保存 | `review_status=NEEDS_INPUT`，`draft.saved=false` | `request_M02_missing.trace.json` |
| 规则风险 | `request_M03_risk` | 阻断 | `review_status=RISK_BLOCKED`，未查询时段、未保存 | `request_M03_risk.trace.json` |
| 时段冲突 | `request_M01_conflict` | 提出 19:00 替代，标记待确认 | `suggested_slot.time=19:00`，`alternative=true`，`hard_requirement_modified=false`，`requested_slot.time=18:00` | `request_M01_conflict.trace.json` |
| 重复提交 | 同一请求再跑一次 | 返回同一草稿 | `draft.duplicate=true`，`draft_id` 相同；`drafts.json` 中 M01 只有 1 条 | `request_M01_duplicate.second.trace.json` |
| 保存失败 | `--inject save_fail` | 明确失败 | `status=SAVE_FAILED`，`draft.saved=false`，`draft.error.code=SAVE_FAILED` | `request_M05_normal.savefail.trace.json` |
| 步数上限 | `--max-steps 2` | 未完成 | `status=INCOMPLETE`，保留 `collected.material` | `request_M01_conflict.limit.trace.json` |

## 两条执行路径（Trace 对照）

**正常路径**（`request_M05_normal.trace.json`）：

```
get_material  →  check_rules  →  query_slots(2026-11-05, 20:00)
              →  save_draft(2026-11-05, 20:00)  →  finish
```

**冲突调整路径**（`request_M01_conflict.trace.json`）：

```
get_material  →  check_rules  →  query_slots(2026-11-05, 18:00)
              →  观察到 18:00 被占用、候选 19:00/20:00
              →  save_draft(2026-11-05, 19:00)  →  finish（替代时段待确认）
```

**阻断路径**（`request_M03_risk.trace.json`）：

```
get_material  →  check_rules  →  命中 R01（版权 high）→  finish（RISK_BLOCKED）
```

三条路径的动作与步数不同，说明决策会随工具返回改变，而不是固定串行调用。

## 失败注入与边界

- 保存失败：`--inject save_fail` 使 `save_draft` 抛 `ToolError`；Agent 不重试、不保存、不声称成功，结果为 `SAVE_FAILED`；
- 步数上限：`--max-steps 2` 只允许两次工具调用，第二次后即返回 `INCOMPLETE`，并保留已读取的素材信息；
- 工具调用上限：`--max-tool-calls 2` 同样返回 `INCOMPLETE`，`tool_calls_used=2`；
- 重复提交：`drafts.json` 中 M01 仅 1 条记录，两条 Trace 的 `draft_id` 一致。

## 未覆盖与限制

- 真实大模型的决策质量未验证（Mock 只验证流程；真实适配层需要 API Key）；
- 未做并发写入与真实数据库，文件存储在并发下可能产生竞争；
- 规则引擎只覆盖示例中的 4 条规则，未做通用规则 DSL；
- 未接入真实发布系统（题目要求只保存草稿）。

## 健壮性补充测试

除 6 个验收点外，额外覆盖输入异常与命令行行为：

| 场景 | 期望 | 实测 |
|---|---|---|
| 带 BOM 的 JSON 请求 | 正常解析 | `exit=0`，`NEEDS_CONFIRMATION` |
| 非法 JSON / 文件不存在 | 结构化错误，不抛 traceback | `exit=2`，`status=ERROR` |
| `material_id` 为空 | 结构化错误 | `exit=2`，`请求无效: 缺少 material_id` |
| 素材不存在（M99） | 请求补充信息 | `exit=0`，`NEEDS_INPUT` |
| 日期不在排期数据中（2026-12-01） | 搜索窗口内无时段 → 阻断 | `exit=0`，`NO_SLOT` |
| 缺少发布时间 | 请求补充信息 | `exit=0`，`NEEDS_INPUT` |

## 复测记录

- `pytest -q` 连续运行 3 次，均为 `34 passed`，无随机失败；
- 将仓库复制到独立临时目录（不含 `.git`）后，重新执行 `pytest` 与 `scripts/run_examples.py`，结果一致：测试全过、示例可重新生成、`drafts.json` 仍为 2 条（M01/M05）；
- 代码与测试中无绝对路径依赖。
