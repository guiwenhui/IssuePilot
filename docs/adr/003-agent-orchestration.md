# ADR-003：Agent 工作流编排

- Status: Accepted
- Date: 2026-08-13

## Context

IssuePilot 需要确定性的检索、分析、计划、审批、Patch、测试与审查顺序，还需要暂停恢复和有限重试。单 Agent 工具循环实现简单，但状态、权限边界和终止条件容易隐藏在 Prompt 中；自由对话式多 Agent 也难以稳定控制成本与结束条件。

## Decision

从 M5 起使用 LangGraph 显式状态图。每个节点具有明确输入、输出、允许修改的状态字段与下一步。角色优先实现为节点，不为展示“多 Agent”而创建自由对话角色。

M6 使用 Checkpoint 持久化安全节点状态，并使用 Interrupt 在计划批准处暂停。M8 加入按错误类型区分的有限重试和人工升级。

## Alternatives

### 单 Agent 加工具循环

优点是代码少、原型快。缺点是审批、状态转换、工具权限和循环终止容易依赖提示词，难以测试和恢复。

### CrewAI 或 AutoGen 式多 Agent 对话

优点是角色表达直观、协作演示效果好。缺点是消息数量、终止条件、成本和副作用控制更难预测。

### 普通 Python 状态机

优点是依赖少且完全可控。缺点是需要自行实现 Checkpoint、Interrupt、图可视化和运行时集成。

## Consequences

- 节点状态和路由显式可见，便于理解、测试和评测。
- Checkpoint 支持从安全节点恢复，但不保存模型完整思考过程。
- 状态 Schema 和节点边界需要额外设计，代码量高于简单 Agent 循环。
- 高风险工具仍受安全层与人工审批约束，LangGraph 本身不是授权机制。
