# examples

- `inputs/`：7 个请求（正常、冲突、信息缺失、风险、无可用时段、重复提交、保存失败复用）。
- `outputs/`：Mock 策略的实际运行结果与 Trace。
- `traces/openai/`：真实模型（DeepSeek `deepseek-chat`）运行结果与 Trace（normal / conflict / risk）。
- `test-report.txt`：`pytest` 完整输出（66 passed）。

| 场景 | 结果 | Trace |
|---|---|---|
| 正常排期 | `request_M05_normal.result.json` | `request_M05_normal.trace.json` |
| 时段冲突 | `request_M01_conflict.result.json` | `request_M01_conflict.trace.json` |
| 信息缺失 | `request_M02_missing.result.json` | `request_M02_missing.trace.json` |
| 规则风险 | `request_M03_risk.result.json` | `request_M03_risk.trace.json` |
| 无可用时段 | `request_M04_no_slot.result.json` | `request_M04_no_slot.trace.json` |
| 重复提交（第二次） | `request_M01_duplicate.second.result.json` | `request_M01_duplicate.second.trace.json` |
| 保存失败 | `request_M05_normal.savefail.result.json` | `request_M05_normal.savefail.trace.json` |
| 步数上限 | `request_M01_conflict.limit.result.json` | `request_M01_conflict.limit.trace.json` |

`drafts.json` 为运行后的草稿存储，可核对重复提交只产生一份 M01 草稿。
