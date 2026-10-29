# 素材审核与发布排期 Agent

小影科技 2027 校招 AI Agent 开发岗笔试题 1。  
输入素材与发布时间要求，输出审核状态、风险原因、建议时段、待确认项与草稿保存结果；**只保存草稿，不做任何发布**。

## 环境

- Python 3.10+
- 运行时零第三方依赖（标准库实现）
- 测试依赖：`pytest>=8.0`

```bash
pip install -r requirements.txt
```

## 运行

单场景（默认离线 Mock 策略）：

```bash
python -m src.cli \
  --request examples/inputs/request_M01_conflict.json \
  --outdir examples/outputs
```

常用参数：

```bash
# 草稿保存失败注入
python -m src.cli --request examples/inputs/request_M05_normal.json \
  --inject save_fail --outdir examples/outputs --tag savefail

# 降低步数上限，验证"达到上限返回未完成"
python -m src.cli --request examples/inputs/request_M01_conflict.json \
  --max-steps 2 --outdir examples/outputs --tag limit

# 重复提交：使用同一个 --store，再跑一次相同请求
python -m src.cli --request examples/inputs/request_M01_duplicate.json \
  --store examples/outputs/drafts.json --outdir examples/outputs --tag second
```

批量生成全部示例（覆盖 6 个验收点 + 2 条额外路径）：

```bash
python scripts/run_examples.py
```

测试：

```bash
pytest
```

## 目录

```
src/
  agent.py        Agent 主循环：决策 → 工具 → 观察 → 再决策，含步数/工具调用上限
  policy.py       离线 Mock 策略（模拟模型的下一步选择），动作协议与真实模型一致
  tools.py        素材读取 / 规则检查 / 时段查询 / 草稿保存（幂等）
  guards.py       禁止发布、硬性要求只读、请求校验
  schemas.py      请求、素材、风险、状态枚举
  cli.py          命令行入口
  llm/            可选真实模型适配（默认不启用）
tests/            单元 + 集成 + 边界测试（28 条）
examples/
  inputs/         场景输入
  outputs/        实际运行结果与 Trace
data/             合成素材、规则、时段
docs/             需求、方案、评估、AI 使用、复盘
scripts/          示例批量生成脚本
```

## 决策循环

动作集合：`get_material`、`check_rules`、`query_slots`、`save_draft`、`finish`。  
每一步记录：决策依据、工具与参数、返回摘要、下一步动作，写入 Trace（`examples/outputs/*.trace.json`）。

- 风险高 → 阻断（不查询时段、不保存草稿）
- 信息缺失 → 请求补充（不保存草稿）
- 目标时段被占 → 提出替代时段并标记待确认，**不修改用户硬性要求**
- 保存失败 → 返回 `SAVE_FAILED`，明确"未生成草稿"
- 相同请求重复提交 → 幂等键命中，返回同一 `draft_id`，不新增草稿
- 达到 `max_steps` / `max_tool_calls` → 返回 `INCOMPLETE` 并保留已获取结果

## 输出字段

| 字段 | 说明 |
|---|---|
| `review_status` | 审核结论：PASS / NEEDS_INPUT / RISK_BLOCKED / NO_SLOT / SAVE_FAILED / INCOMPLETE |
| `risk_reasons` | 命中的规则原因 |
| `suggested_slot` | 建议时段；`alternative=true` 表示与用户原要求不同 |
| `pending_items` | 待确认项（替代时段、需复核的风险、草稿确认） |
| `draft` | 草稿状态：`saved`、`draft_id`、`duplicate`；失败时带 `error` |
| `published` | 恒为 `false`（本项目不发布） |

## 验收点与示例

| 验收点 | 输入 | 结果文件 |
|---|---|---|
| 正常排期 | `request_M05_normal` | `examples/outputs/request_M05_normal.result.json` |
| 信息缺失 | `request_M02_missing` | `request_M02_missing.result.json` |
| 规则风险 | `request_M03_risk` | `request_M03_risk.result.json` |
| 时段冲突 | `request_M01_conflict` | `request_M01_conflict.result.json` |
| 重复提交 | `request_M01_conflict` + `request_M01_duplicate` | `request_M01_duplicate.second.result.json`，`drafts.json` 仅 1 条 M01 草稿 |
| 保存失败 | `request_M05_normal` + `--inject save_fail` | `request_M05_normal.savefail.result.json` |
| 步数上限 | `request_M01_conflict --max-steps 2` | `request_M01_conflict.limit.result.json` |

## Mock 边界

- 默认使用 `MockPolicy`（离线规则策略）模拟"模型选择动作"，用于验证流程、状态与边界；
- 它只能证明流程与工程实现，不代表真实大模型的决策质量；
- 真实模型适配层在 `src/llm/openai_policy.py`，需要 `OPENAI_API_KEY`，未纳入自动化测试。

## 已知限制

- 单进程、文件存储；未做并发写锁与真实数据库；
- 未接入真实发布系统（按题意仅保存草稿）；
- 规则引擎只覆盖示例中的四类规则，未做通用 DSL；
- 真实模型的工具调用稳定性未验证。

## 提交信息

- 题号：1（素材审核与发布排期 Agent）
- 运行入口：`python -m src.cli`
- 测试入口：`pytest`
- 示例入口：`python scripts/run_examples.py`
