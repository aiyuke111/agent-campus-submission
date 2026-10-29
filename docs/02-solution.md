# 02 方案

## 总体结构

```
请求 JSON（支持批量）
   │  校验：material_id / publish_date / publish_time / hard 类型
   ▼
Agent 主循环（src/agent.py）
   │  1) 模型决策（MockPolicy 或 OpenAIPolicy）
   │  2) 动作名/结构校验 → 禁止发布动作
   │  3) 前置条件守卫（src/guards.py）：不能跳过审核、不能篡改参数
   │  4) 执行工具（src/tools.py）
   │  5) 结束结论证据校验：不信任模型自报的 status
   ▼
结果 + Trace
```

## 动作协议

```json
{"action": "query_slots", "args": {"date": "2026-11-05", "requested_time": "18:00"}, "decision_basis": "规则检查通过，查询时段占用"}
```

动作集合：`get_material`、`check_rules`、`query_slots`、`save_draft`、`finish`。  
`finish` 必须带 `status`、`review_status`、`reason`、`pending`，但**这些字段只是"声明"，Agent 会用真实工具状态复核**。

## 动态决策

| 观察到的结果 | 下一步动作 | 依据 |
|---|---|---|
| 请求格式非法（日期/时间/hard） | `finish` → `NEEDS_INPUT` | 无法排期，先修输入 |
| 素材必填字段缺失 | `finish` → `NEEDS_INPUT` | 审核信息不足 |
| 命中高风险规则 | `finish` → `RISK_BLOCKED` | 版权/敏感未处理，禁止排期 |
| 目标时段已占用、有候选 | `save_draft` 保存候选，标记 `alternative=true` | 保证可执行，同时保留用户原要求 |
| 当天无候选 | 继续 `query_slots` 查相邻日期（最多 `search_days` 天） | 给运营可选方案 |
| 窗口内都没有可用时段 | `finish` → `NO_SLOT` | 无解时如实返回缺口 |
| `save_draft` 抛错 | `finish` → `SAVE_FAILED`，不重试、不虚报 | 失败即失败，避免重复副作用 |
| 步数/工具调用达到上限 | `INCOMPLETE`，附已获取结果 | 有界执行 |

两条典型路径（Trace 见 `examples/outputs/`）：

- 正常：`get_material → check_rules → query_slots → save_draft → finish`（5 步 / 4 次工具）
- 阻断：`get_material → check_rules → finish`（3 步 / 2 次工具，不查询时段）

## 结束结论的证据校验（防虚报）

`Agent._validate_finish` 用真实状态校验模型声明：

| 模型声明 | 必须满足的证据 | 不满足时 |
|---|---|---|
| `NEEDS_CONFIRMATION` | 已保存草稿、已做规则检查、无高风险、已查时段 | 强制改为 `ERROR`，记录 `claim_violations` |
| `review_status=PASS` | 已做规则检查且无高风险 | 改为 `ERROR` |
| `SAVE_FAILED` | 草稿未保存且存在保存错误 | 改为 `ERROR` |
| `BLOCKED` | 有高风险记录或已查时段且无候选 | 改为 `ERROR` |
| `NEEDS_INPUT` | 存在输入错误/素材缺失/素材不存在 | 改为 `ERROR` |

## 动作前置条件（防跳过审核）

`guards.check_preconditions` 在调用工具前检查上下文：

- `check_rules` 前必须先 `get_material`；
- `query_slots` 前必须完成规则检查，且无高风险；
- `save_draft` 前必须：素材完整、规则已查、无高风险、已查时段、存在建议时段；
- 保存参数必须与"已确认的建议时段"一致，且 `requested_time`、`hard` 不能被模型改写。

违反时抛 `RejectedAction`，Agent 返回结构化 `ERROR` 并在 Trace 中标记 `rejected`，不会崩溃。

## 排期一致性

- `query_slots(date, time, material_id)` 会把**其他素材**的草稿视为已占用；同一素材自己的草稿不占用（否则重复提交会因自己占用而上一次建议的时段而重新排期）；
- `save_draft` 在**文件锁内**重新读库，先查幂等键，再查"同一时段是否被其他素材占用"，最后原子写盘；
- 写入流程：临时文件 → `fsync` → `os.replace`；失败清理临时文件并抛 `ToolError(SAVE_FAILED)`，内存状态不提交；
- 并发：`msvcrt`（Windows）/`fcntl`（POSIX）文件锁；跨进程同时保存时，后到者会看到新占用并按冲突处理。

## 幂等键

```text
sha256(material_id | date | time | requested_time | hard | rules_version)[:16]
```

- 相同请求重复提交 → 命中同一键，返回原 `draft_id`，`duplicate=true`；
- 同一素材不同要求时间（如 18:00 vs 17:00）→ 不同键，保留各自意图；
- 换时段 → 新键、新草稿。

## 输入与配置

- `Request.from_dict` 校验：`material_id` 非空、日期 `YYYY-MM-DD` 且真实存在、时间 `HH:MM` 合法、`hard` 必须是布尔值（兼容字符串 `"true"/"false"`）；
- 非法输入 → `NEEDS_INPUT` 并列出具体字段，不抛异常、不误报 `NO_SLOT`；
- `search_days` 从 `data/slots.json` 读取并注入策略，避免配置与代码漂移；
- 候选时段优先"不早于用户要求"；当天只有更早的空闲时段时才向前推荐，并标记待确认。

## 模型接入

- 默认 `MockPolicy`：离线、确定性，方便评审复现；
- `--policy openai`：真实模型，动作协议一致；网络异常、空响应、非 JSON、未知动作统一抛 `PolicyError`，由 Agent 转结构化 `ERROR`；
- 适配器支持注入 client，单元测试覆盖正常 JSON、坏 JSON、空响应、未知动作、网络异常；
- 评测环境无 API Key，因此真实模型的线上效果不在本次运行记录内。

## 技术取舍

- 标准库实现：运行时零依赖，评审环境直接可跑；
- 业务确定性下沉到工具与守卫，模型只负责"下一步选择"，便于测试与替换模型；
- 文件存储 + 文件锁：单机演示足够；数据库/分布式锁留到下一步。
