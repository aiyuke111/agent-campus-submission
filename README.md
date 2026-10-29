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

# 批量请求（可重复 --request，共享同一个草稿库）
python -m src.cli --request examples/inputs/request_M05_normal.json \
  --request examples/inputs/request_M01_conflict.json --outdir examples/outputs

# 真实模型策略（需要 OPENAI_API_KEY；默认 mock 便于离线复现）
python -m src.cli --request examples/inputs/request_M01_conflict.json --policy openai
```

批量生成全部示例（覆盖 6 个验收点 + 2 条额外路径）：

```bash
python scripts/run_examples.py
```

测试：

```bash
pytest
```

CLI 退出码：`0` 表示正常执行（无论业务结论），`2` 表示请求文件不可读或系统配置错误。请求文件支持带 BOM 的 UTF-8。

## 目录

```
src/
  agent.py        Agent 主循环：决策 → 工具 → 观察 → 再决策；含结束结论证据校验
  policy.py       离线 Mock 策略（真实模型动作协议一致）
  tools.py        素材 / 规则 / 时段 / 草稿保存（幂等、原子写、文件锁）
  guards.py       禁止发布、动作前置条件、参数防篡改
  schemas.py      请求校验、素材、风险、状态枚举
  cli.py          命令行入口（支持批量请求与真实模型策略）
  llm/            真实模型适配（OpenAI 兼容，可注入 client 测试）
tests/            单元 + 集成 + 反例/加固测试（64 条）
examples/
  inputs/         场景输入
  outputs/        实际运行结果与 Trace
data/             合成素材、规则、时段
docs/             需求、方案、评估、AI 使用、复盘
scripts/          示例批量生成脚本
```

## 决策循环与安全边界

动作集合：`get_material`、`check_rules`、`query_slots`、`save_draft`、`finish`。  
每步记录：决策依据、工具与参数、返回摘要、下一步动作，写入 Trace（`examples/outputs/*.trace.json`）。

**Agent 不信任模型的结论，全部校验：**

- 保存前置条件：必须已读素材、已做规则检查、无高风险、已查询时段，且保存参数与"已确认的建议时段"一致；
- 结束结论校验：`NEEDS_CONFIRMATION` 必须存在真实已保存草稿；`PASS` 必须真的做过规则检查且无高风险；`SAVE_FAILED` 不得与"已保存"矛盾；
- 越权/未知动作、模型超时/非 JSON/缺字段，全部转成结构化 `ERROR`，不抛 traceback；
- 输入校验：日期、时间、`hard` 类型非法 → `NEEDS_INPUT`，不会崩溃；
- 只存草稿：代码与状态机中没有发布动作，`published` 恒为 `false`。

**排期一致性：**

- 时段查询会读取已保存草稿的占用（不同素材不能占用同一时段）；
- 保存前在文件锁内重新检查时段冲突与幂等键，避免"查询后被人抢走"的竞态；
- 草稿写入采用临时文件 + 原子替换，写盘失败不会污染内存状态，也不会误报成功；
- 幂等键包含素材、日期、时段、用户要求时间与 `hard` 标志，同一请求重复提交只生成一份草稿；
- 达到 `max_steps` / `max_tool_calls` → `INCOMPLETE` 并保留已获取结果。

## 输出字段

| 字段 | 说明 |
|---|---|
| `review_status` | 审核结论：PASS / NEEDS_INPUT / RISK_BLOCKED / NO_SLOT / SAVE_FAILED / INCOMPLETE / ERROR |
| `risk_reasons` | 命中的规则原因 |
| `suggested_slot` | 建议时段；`alternative=true` 表示与用户原要求不同 |
| `pending_items` | 待确认项（替代时段、需复核的风险、草稿确认、输入问题） |
| `draft` | 草稿状态：`saved`、`draft_id`、`duplicate`；失败时带 `error` |
| `evidence` | 本次运行的证据开关：`rules_checked`、`slot_checked`、`draft_saved` |
| `claim_violations` | 模型结束结论与证据不符时的违规项（正常为空） |
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

- 默认 `MockPolicy` 用于离线复现流程、状态与边界；它不代表真实模型的决策质量。
- 真实模型入口已接通 CLI（`--policy openai`），适配层对网络异常、空响应、非 JSON、未知动作做了结构化处理，并用注入 client 做了单元测试。
- 评测环境无 API Key，因此真实模型的线上效果未纳入本次运行记录。

## 已知限制

- 文件存储 + 文件锁，适合单机；未接入数据库与分布式锁；
- 多进程并发只做了锁与"保存时二次校验"的防护，未做大压力测试；
- 规则引擎覆盖示例中的四类规则，未抽象通用 DSL；
- 未接入真实发布系统（按题意仅保存草稿）。

## 提交信息

- 题号：1（素材审核与发布排期 Agent）
- GitHub URL：`https://github.com/<your-account>/<repo>`（推送后填写）
- 最终 commit SHA：以 `git rev-parse HEAD` 为准（见答题页）
- 运行入口：`python -m src.cli`
- 测试入口：`pytest`
- 示例入口：`python scripts/run_examples.py`
