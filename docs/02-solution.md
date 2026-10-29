# 02 方案

## 总体结构

```
请求 JSON
   │
   ▼
Agent 主循环（src/agent.py）
   │  决策（src/policy.py：Mock 策略 / 可选真实模型）
   │  动作守卫（src/guards.py：禁止发布、参数校验）
   ▼
工具层（src/tools.py）
   ├─ get_material  读取素材元数据、检查必填字段
   ├─ check_rules   规则匹配，输出 high / medium 风险
   ├─ query_slots   查询目标日期时段占用，返回占用与候选时段
   └─ save_draft    幂等保存草稿（失败抛错）
   │
   ▼
结果 + Trace（CLI 输出、examples/outputs/*.trace.json）
```

## 动作协议

每步只做一个动作，模型输出统一为：

```json
{"action": "query_slots", "args": {"date": "2026-11-05", "requested_time": "18:00"}, "decision_basis": "规则检查通过，查询时段占用"}
```

动作集合：`get_material`、`check_rules`、`query_slots`、`save_draft`、`finish`。  
`finish` 携带 `status`、`review_status`、`reason`、`pending`。

## 动态决策

| 观察到的结果 | 下一步动作 | 依据 |
|---|---|---|
| 素材必填字段缺失 | `finish` → `NEEDS_INPUT` | 无法完成审核，先让运营补资料 |
| 命中高风险规则 | `finish` → `RISK_BLOCKED` | 版权/敏感未处理，不允许进入排期 |
| 目标时段已占用、有候选 | `save_draft` 保存候选时段，标记 `alternative=true` | 优先保证可执行，同时保留用户原要求 |
| 目标时段已占用、当天无候选 | 继续 `query_slots` 查相邻日期（最多 3 天） | 避免直接失败，给运营可选方案 |
| 窗口内都没有可用时段 | `finish` → `NO_SLOT` | 无解时如实返回缺口 |
| `save_draft` 抛错 | `finish` → `SAVE_FAILED`，不重试、不虚报 | 失败即失败，避免重复副作用 |
| 步数/工具调用达到上限 | `finish` → `INCOMPLETE`，附已获取结果 | 有界执行，防止死循环 |

两条典型路径（Trace 见 `examples/outputs/`）：

- 正常路径：`get_material → check_rules → query_slots → save_draft → finish`（5 步 / 4 次工具）
- 阻断路径：`get_material → check_rules → finish`（3 步 / 2 次工具，不查询时段）

## 状态机

```
NEEDS_INPUT / RISK_BLOCKED / NO_SLOT / SAVE_FAILED / INCOMPLETE
                    ▲
                    │（任一分支终止）
请求 ──► 读取素材 ──► 规则检查 ──► 时段查询 ──► 保存草稿 ──► NEEDS_CONFIRMATION
```

`published` 不在状态机中，代码与数据里都没有发布字段的取值入口。

## 幂等与防重复

- 幂等键：`sha256(material_id | date | time | rules_version)` 前 16 位；
- 同一请求重复提交命中已有键 → 返回原 `draft_id`，`duplicate=true`，存储不新增；
- 换时段属于新的排期意图 → 新键、新草稿（符合业务预期）。

## 边界与失败处理

- `guards.assert_action_allowed`：发布类动作直接抛错；
- 硬性要求：替代时段只在 `suggested_slot` 中体现，`hard_requirement_modified` 恒为 `false`；
- 工具错误统一 `ToolError(code, message)` 向上抛，Agent 转成“未成功”的结果，不会把失败步骤记为成功；
- 保存失败后不再自动重试，避免在不确定状态下产生多份草稿。

## 技术取舍

- **标准库实现**：运行时零依赖，评审环境直接可跑；Pydantic 等留到有真实模型与数据库时再引入。
- **Mock 策略而非真实模型**：题面允许离线 Mock；策略是确定性的，测试可稳定复现。真实模型适配层保留同一动作协议。
- **工具只做本地实现**：素材/规则/时段均为合成数据，符合题目“业务工具可用本地函数或 Mock”。
- **文件存储**：单进程演示足够；并发与一致性在“已知限制”中说明。

## Mock 边界

`MockPolicy` 用固定规则模拟“模型选择下一步”，只验证流程、状态与边界，不证明真实模型的决策质量。  
真实模型路径（`src/llm/openai_policy.py`）需要 API Key，且未纳入测试覆盖。
