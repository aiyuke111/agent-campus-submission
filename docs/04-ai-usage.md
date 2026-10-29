# 04 AI 使用记录

## 使用范围

- 代码骨架：目录结构、dataclass 定义、CLI 参数解析、pytest 文件组织；
- 文档提纲：README 与 docs 的章节安排；
- 测试用例清单：验收点到测试函数的映射建议；
- 代码审查：静态检查建议（未引入额外工具链）。

## AI 与个人贡献对照

| 部分 | AI 辅助内容 | 个人修改/决策 | 验证方式 |
|---|---|---|---|
| 工程骨架 | 目录与文件骨架、CLI 参数框架 | 重构模块边界、统一错误类型、精简依赖 | `pytest` 66 条 |
| 业务规则 | 规则表初稿 | 确定 R01–R04 的严重级别与是否需确认 | 验收测试 + 示例 Trace |
| Agent 循环 | 循环框架建议 | 结束结论证据校验、前置条件守卫、重复动作防护、步数/工具上限 | 反例测试（test_hardening） |
| 排期一致性 | 幂等思路 | 幂等键加入 `requested_time`/`hard`；查询/保存纳入草稿占用；锁内二次校验 | 并发抢时段实测 |
| 存储可靠性 | 原子写思路 | 临时文件 + `fsync` + `os.replace`；失败不提交内存 | 故障注入测试 |
| 真实模型接入 | 适配器骨架 | 零依赖 HTTP 客户端、`progress/allowed_actions` 提示、review 归一化 | `examples/traces/openai/` 实际运行 |
| 文档 | 章节提纲与初稿 | 按实际运行结果重写指标、失败与限制 | 与 Trace 逐条核对 |

## 关键设计决定（人工）

- 状态枚举：`NEEDS_CONFIRMATION / NEEDS_INPUT / BLOCKED / SAVE_FAILED / INCOMPLETE / ERROR`；
- 幂等键：`sha256(material_id + date + time + requested_time + hard + rules_version)`，重复提交返回同一 `draft_id`；
- 边界守卫：发布动作拦截、硬性要求只读、结论必须有工具证据、失败不得虚报；
- Trace 字段：步骤、工具参数、返回摘要、下一步、决策依据；
- 示例数据与测试断言：按 6 个验收点逐条对齐实际输出。

## 验证方式

1. `pytest -q`：66 条测试全部通过（连续跑 3 次无失败）；
2. `python scripts/run_examples.py`：8 个 Mock 场景实际运行，结果与 Trace 落盘；
3. `python scripts/run_openai_examples.py`：用真实 DeepSeek 模型跑 3 条路径，Trace 落盘到 `examples/traces/openai/`；
4. 人工核对 `examples/outputs/*.trace.json` 与 `examples/traces/openai/*.trace.json` 的动作序列与字段；
5. 手工执行 README 中的 CLI 命令（含 `--inject save_fail`、`--max-steps 2`）。

## 未使用 AI 或不可验证的部分

- 未调用真实大模型 API 来生成项目代码；项目内的真实模型调用仅用于产出 `examples/traces/openai/` 的运行记录；
- 真实模型调用使用运行环境提供的 Key，未写入仓库、未落盘到任何 Trace；
- 未使用真实业务数据或隐私数据，全部为合成数据；
- 真实模型只验证了 DeepSeek `deepseek-chat` 一个模型，并发写入、线上发布未验证。
