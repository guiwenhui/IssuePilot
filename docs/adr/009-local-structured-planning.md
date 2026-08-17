# ADR-009：M5 本地结构化需求规划

- Status: Accepted
- Date: 2026-08-17

## Context

M4 已保存可解释的代码证据，但用户仍需把 Issue、相关实现点、验收标准、步骤和测试策略人工串联。M5 要验证显式 Agent 图的价值，同时必须避免代码证据离开本机、模型自由引用不存在文件，以及提前引入 M6 的审批恢复复杂度。

## Decision

使用 LangGraph 1.2 固定四节点图：`retrieve_code → analyze_requirement → create_plan → persist_plan`。图不配置 Checkpointer、Interrupt、工具或循环。M4 成功后在同一检索事务进入 `analyzing`；图成功后在单一事务保存 `planning_runs`、`requirement_analyses`、`implementation_plans` 并进入 `waiting_approval`。

Chat Provider 直接通过 `httpx` 调用 loopback Ollama `/api/chat`，固定 `qwen3:8b`、`think=false`、temperature 0、16K context 和 JSON Schema。Evidence 最多 10 条、单条 3,000 字符、总计 20,000 字符，保存稳定 SHA256 与裁剪标记。Pydantic 之后再验证所有 rank、path、symbol 均来自 Evidence，并拒绝代码块和 Diff 标记。

Ollama 0.32.13 实机验证发现 grammar 不接受 Pydantic 的 `minLength/maxLength`。Provider 只从发送给 Ollama 的兼容 Schema 移除这两个关键字；响应体积上限、完整 Pydantic 字符长度/列表数量约束和 Evidence Validator 仍全部执行，因此不是放宽业务契约。

读取 Planning 时同时核对 Repository Snapshot、Code Index、Retrieval Run、Planning Run 和真实 Worktree HEAD/clean。`PLANNING_ENABLED=false` 使新任务回到 M4 `retrieved`；历史任务不自动补排。

## Alternatives

### OpenAI、Gemini 或其他托管 Chat 模型

可能提供更高质量和更稳定吞吐，但代码证据会离开本机，并新增密钥、费用、限流和数据治理边界。Provider 接口保留未来受控替换能力，M5 不启用。

### 普通 Python 顺序函数

依赖更少且足以完成四步流程，但不能直接验证后续 Checkpoint/Interrupt 所需的图边界。固定 LangGraph 图的额外复杂度可控。

### M5 直接加入 Checkpoint 和审批

可一次形成完整暂停恢复，但会同时引入两套权威状态、一致性恢复和新 API，难以定位错误。该能力按计划留给 M6。

## Consequences

- 公开代码证据和模型推理保留在本机；需要约 5.2 GB 的 `qwen3:8b` 与足够内存。
- Structured Output 与确定性引用校验提高可审查性，但不能保证计划在业务语义上必然正确，所以必须停在 `waiting_approval`。
- 模型调用期间服务重启会使任务停在 `analyzing`；M6 才提供持久恢复。
- 三张规划表保留模型、Prompt、Graph 和证据版本，可做复现与后续评测。
- M5 不写仓库、不生成 Patch、不执行测试、不 Commit/Push/PR。
