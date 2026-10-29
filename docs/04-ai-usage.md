# 04 AI 使用记录

## 使用范围

- 代码骨架：目录结构、dataclass 定义、CLI 参数解析、pytest 文件组织；
- 文档提纲：README 与 docs 的章节安排；
- 测试用例清单：验收点到测试函数的映射建议；
- 代码审查：静态检查建议（未引入额外工具链）。

## 人工修改与决策

以下内容由本人确定并逐行核对：

- 业务规则：R01 版权阻断、R02 敏感阻断、R03 时长确认、R04 品牌确认；
- 状态枚举与状态机：`NEEDS_CONFIRMATION / NEEDS_INPUT / BLOCKED / SAVE_FAILED / INCOMPLETE`；
- 幂等键设计：`material_id + date + time + rules_version` 的哈希，重复提交返回同一 `draft_id`；
- 边界守卫：发布动作拦截、硬性要求只读、失败不得虚报；
- Trace 字段：步骤、工具参数、返回摘要、下一步、决策依据；
- 示例数据与测试断言：按 6 个验收点逐条对齐实际输出。

## 验证方式

1. `pytest -q`：64 条测试全部通过（连续跑 3 次无失败）；
2. `python scripts/run_examples.py`：8 个场景实际运行，结果与 Trace 落盘；
3. 人工核对 `examples/outputs/*.trace.json` 的动作序列与字段；
4. 手工执行 README 中的 CLI 命令（含 `--inject save_fail`、`--max-steps 2`）。

## 未使用 AI 或不可验证的部分

- 未调用任何真实大模型 API；
- 未使用真实业务数据或密钥，全部为合成数据；
- 真实模型下的决策稳定性、并发写入、线上发布未验证。
