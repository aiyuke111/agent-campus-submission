# 01 需求

## 用户与目标

内容运营在发布前需要确认：哪些素材可以排、什么时候排、有什么风险、是否已保存草稿。  
本 Agent 的目标是**形成一份无冲突、可确认的发布排期草稿**，并把风险与待确认项显式交回给运营。

## 输入

| 输入 | 来源 | 说明 |
|---|---|---|
| 素材 ID | 请求 JSON | 必填 |
| 元数据 | `data/materials.json` | 版权、敏感标记、时长、品类 |
| 发布时间要求 | 请求 JSON | 日期 + 时间；`hard=true` 表示用户硬性要求 |
| 审核规则 | `data/rules.json` | 高风险阻断、中风险需确认 |
| 已有排期 | `data/slots.json` | 各日期时段的容量与占用 |

## 输出

| 字段 | 含义 |
|---|---|
| `review_status` | 审核结论：PASS / NEEDS_INPUT / RISK_BLOCKED / NO_SLOT / SAVE_FAILED / INCOMPLETE |
| `risk_reasons` | 命中规则的原因清单 |
| `suggested_slot` | 建议时段；`alternative=true` 表示与用户原要求不同 |
| `pending_items` | 待确认项（替代时段、需复核风险、草稿确认） |
| `draft` | `saved`、`draft_id`、`duplicate`；失败时带 `error` |
| `published` | 恒为 `false` |

## 范围

做：

- 读取素材与规则、查询时段占用、计算替代时段、保存排期草稿；
- 风险分级（阻断 / 需确认）、硬性要求只读、重复提交幂等；
- 步数与工具调用上限，超限返回未完成；
- 全流程 Trace（步骤、参数、返回摘要、下一步、决策依据）。

不做：

- 不做真实发布，不接发布平台；
- 不做素材内容审核（只消费已有元数据）；
- 不做多用户并发与权限系统。

## 成功标准（验收点）

| # | 验收点 | 期望行为 | 对应场景 |
|---|---|---|---|
| 1 | 正常排期 | 无风险、时段可用 → 保存草稿，状态待确认，不发布 | `request_M05_normal` |
| 2 | 素材信息缺失 | 缺必填元数据 → 请求补充，不保存 | `request_M02_missing` |
| 3 | 规则风险 | 命中高风险 → 阻断，不查询时段、不保存 | `request_M03_risk` |
| 4 | 时段冲突 | 目标时段被占 → 给出替代时段并标记待确认；原要求不被修改 | `request_M01_conflict` |
| 5 | 重复提交 | 相同请求重复保存 → 仅一份草稿，返回同一 draft_id | `request_M01_conflict` + `request_M01_duplicate` |
| 6 | 保存失败 | 保存异常 → 明确失败，不得声称成功 | `request_M05_normal --inject save_fail` |
| 7 | 上限 | 达到步数/工具上限 → 返回 `INCOMPLETE` 且保留已获取结果 | `request_M01_conflict --max-steps 2` |

## 关键约束

- **硬性发布时间只读**：冲突时只能提出替代时段，不能静默改值；
- **只存草稿**：任何情况下 `published=false`，代码中不存在发布动作；
- **失败不得虚报**：保存失败必须返回 `SAVE_FAILED`，草稿状态为 `saved=false`；
- **可追溯**：每次运行输出 Trace，能逐步骤复核决策与工具返回。
