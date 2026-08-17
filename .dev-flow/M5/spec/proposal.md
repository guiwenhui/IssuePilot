# Proposal: M5

> status: approved for implementation
> approved_at: 2026-08-17

## 背景与目标

M4 已将 Issue 与固定 Commit 的代码证据通过关键词、AST Symbol 和向量三路检索关联起来，但用户仍需自行把证据整理为需求、验收标准和实施顺序。M5 首次引入 LangGraph 与单一本地生成式模型，在不修改仓库、不执行测试、不实现审批恢复的前提下，形成可引用、可校验、可持久化的需求分析和实施计划。

成功标准是：新任务完成 M4 检索后进入显式的 `retrieve_code → analyze_requirement → create_plan → persist_plan` 图；最终在 PostgreSQL 原子保存结构化分析、计划和模型/版本证据，任务进入 `waiting_approval`，浏览器刷新后可重新读取相同结果。

## 范围

### 范围内

- 使用 LangGraph `StateGraph` 显式编排读取证据、需求分析、实施规划和持久化节点。
- 使用本机 Ollama `qwen3:8b`，通过 `/api/chat` 和 JSON Schema 生成结构化结果。
- 使用 Provider 协议隔离 Ollama，实现模型不可用、超时和非法响应的稳定错误契约。
- 将需求摘要、验收标准、约束、假设、受影响区域、风险、实施步骤和测试策略保存到 PostgreSQL。
- 所有分析和计划条目引用 M4 Retrieval rank；文件和 Symbol 必须来自传给模型的真实证据。
- 新任务启用 `analyzing` 和 `waiting_approval` 状态；历史 `retrieved` 任务不自动补排。
- 新增只读 Planning API 和 Next.js 分析/计划证据页。
- 使用 `PLANNING_ENABLED` 允许安全退回 M4 终态。
- 将项目 Python 最低版本提升至 3.11，并在 Python 3.13 环境验证。

### 范围外

- LangGraph Checkpoint、Interrupt、批准、修改、拒绝与跨进程恢复（M6）。
- Patch、Unified Diff、Worktree 写入和 `pytest` 执行（M7）。
- Reviewer、自动修复循环和质量 Gate（M8）。
- LangSmith、完整 Trace、Token/延迟看板和对照实验（M9）。
- OpenAI、Gemini、Anthropic、DeepSeek 或其他托管模型调用。
- 工具调用、任意 Shell、仓库文件写入、Commit、Push 或 PR。
- 对升级前 `retrieved` 历史任务进行自动 Backfill。
- 保存或展示模型的 reasoning/thinking trace。

## 验收标准

- **AC1 — 显式图**：给定已完成 M4 检索的新任务，当 Planning 启用时，则 LangGraph 按 `retrieve_code → analyze_requirement → create_plan → persist_plan` 执行，并且图不包含 Checkpoint、Interrupt、工具循环或文件写入节点。
- **AC2 — 一致性**：给定 Snapshot、Code Index、Retrieval Run 或真实 Worktree 的 Commit/clean 状态不一致，当读取证据或 Planning API 时，则停止并返回/保存 `WORKSPACE_INCONSISTENT`，不得复用旧结果。
- **AC3 — 结构化分析**：给定合法的 Issue 和最多 10 条 M4 证据，当分析节点成功时，则输出通过 Pydantic Schema 的摘要、验收标准、约束、假设、受影响区域和风险，且证据 rank 全部存在。
- **AC4 — 结构化计划**：给定已校验分析和证据，当规划节点成功时，则输出 1–12 个有序步骤与测试策略；所有 path、symbol 和 evidence rank 均来自真实输入证据，不包含 Patch 或代码实现。
- **AC5 — 原子持久化**：给定图成功完成，当保存最终结果时，则 Planning Run、Requirement Analysis、Implementation Plan v1 和任务 `waiting_approval` 在一个事务内生效；事务失败时不留下半成品。
- **AC6 — 浏览器恢复**：给定 `waiting_approval` 任务，当用户刷新详情页时，则前端从 FastAPI 重新读取 Tree、Code Structure、Retrieval 和 Planning，展示固定 Commit、模型、分析、计划与证据编号，并停止轮询。
- **AC7 — 稳定失败**：给定 Ollama 不可用、超时、非法 JSON、Schema 不合法、上下文超限或证据引用非法，当图执行时，则任务进入 `failed` 并保存稳定 failure code；已完成的 M2–M4 证据仍可读取。
- **AC8 — 历史兼容**：给定升级前已是 `retrieved` 的任务，当 M5 上线或页面刷新时，则该任务保持历史终态，不自动排队、不调用生成式模型。
- **AC9 — 功能回退**：给定 `PLANNING_ENABLED=false`，当新任务完成 M4 时，则任务继续以 `retrieved` 结束，不构建或调用 Planning Graph。
- **AC10 — 本地与无副作用**：给定任意 Issue 或仓库注释包含诱导性指令，当 M5 执行时，则请求只发送到 loopback Ollama，模型没有工具权限，工作区 HEAD/clean 保持不变且不执行仓库代码。
- **AC11 — 真实模型案例**：给定冻结 MarkupSafe `escape_silent(None)` Issue，当使用真实 `qwen3:8b` 时，则分析和计划 Schema 合法、引用路径全部存在、计划同时包含生产代码和回归测试步骤。

## 影响模块

- `backend/app/agents` —— LangGraph State、Context、节点、Prompt 和图构建。
- `backend/app/llms` —— Chat Provider 协议与 Ollama 实现。
- `backend/app/services` —— Planning Service/Store、一致性与持久化。
- `backend/app/models`、`backend/migrations` —— Planning 数据表及可回退 migration。
- `backend/app/workers`、`backend/app/main.py` —— M4→M5 Pipeline 与运行时装配。
- `backend/app/api`、`backend/app/schemas` —— Planning DTO、只读 endpoint 和错误映射。
- `lib/`、`components/`、`app/` —— 状态轮询、Planning API、分析计划 UI。
- `backend/tests`、前端测试 —— 图、Provider、Schema、Service、Store、API、状态与浏览器回归。
- `README.md`、`docs/`、`.codex/project-config.md` —— M5 真实架构和边界。

## 数据模型

### `planning_runs`

- `id UUID PK`
- `task_id UUID FK tasks ON DELETE CASCADE UNIQUE`
- `retrieval_run_id UUID FK retrieval_runs ON DELETE CASCADE UNIQUE`
- `commit_sha VARCHAR(40)`
- `graph_version VARCHAR(32)`
- `llm_provider VARCHAR(64)`
- `llm_model VARCHAR(256)`
- `analysis_prompt_version VARCHAR(32)`
- `plan_prompt_version VARCHAR(32)`
- `evidence_sha256 VARCHAR(64)`
- `evidence_count INTEGER`
- `evidence_truncated BOOLEAN`
- `created_at TIMESTAMPTZ`

### `requirement_analyses`

- `run_id UUID PK/FK planning_runs ON DELETE CASCADE`
- `summary TEXT`
- `acceptance_criteria JSONB`
- `constraints JSONB`
- `assumptions JSONB`
- `affected_areas JSONB`
- `risks JSONB`

### `implementation_plans`

- `id UUID PK`
- `run_id UUID FK planning_runs ON DELETE CASCADE`
- `version INTEGER`，M5 固定创建 v1
- `status VARCHAR(32)`，M5 固定为 `proposed`
- `steps JSONB`
- `test_strategy JSONB`
- `risk_notes JSONB`
- `created_at TIMESTAMPTZ`
- `UNIQUE(run_id, version)`

## API 契约

### `GET /api/v1/tasks/{task_id}/planning`

成功返回 `200`：

- `task_id`、`commit_sha`
- `run`：Graph、Provider、Model、Prompt 版本、证据数量/是否裁剪、创建时间
- `analysis`：summary、acceptance criteria、constraints、assumptions、affected areas、risks
- `plan`：version、status、ordered steps、test strategy、risk notes

错误保持 `{ error: { code, message, details } }`：

- 非法 UUID：`422 VALIDATION_ERROR`
- 任务不存在：`404 TASK_NOT_FOUND`
- 结果未形成：`409 PLANNING_NOT_READY`
- SHA/工作区不一致：`409 WORKSPACE_INCONSISTENT`
- 数据库不可用：`503 DATABASE_UNAVAILABLE`

M5 不新增任何批准、修改、拒绝或执行类 POST endpoint。

## 接口边界

- Router 只做 HTTP 映射；Planning Service 控制一致性、Graph 调用、失败分类和事务。
- LangGraph State 只保存 JSON 可序列化业务值，不保存数据库 Session、Provider Client 或完整模型思考。
- Runtime Context 注入 Store、Provider、GitClient 和 Workspace；节点不能读取全局可变状态。
- Ollama Provider 只允许 loopback base URL，只负责请求/响应与 Schema 验证，不改变任务状态。
- Store 负责 SQL 和 DTO，不访问 Ollama 或文件系统。
- Next.js 只展示 Planning DTO，不在浏览器重新分析、验证或改变任务状态。

## 状态与流程

M5 新任务成功路径：

```text
retrieving → analyzing → waiting_approval
```

- M4 原子保存 Retrieval 时按 `PLANNING_ENABLED` 选择成功状态：开启为 `analyzing`，关闭为 `retrieved`。
- M5 Graph 仅接受 `analyzing`；重复调用已完成或其他状态时不产生第二份结果。
- M5 任一节点失败进入 `failed`；不自动重试，不从内存伪恢复。
- `waiting_approval` 是 M5 终态，但没有审批动作；M6 才把它接入 Interrupt。
- 历史 `retrieved`、`indexed`、`cloned` 保持各自终态。

## 错误契约

- `LLM_UNAVAILABLE`：Ollama 无法连接、超时或模型不存在。
- `LLM_INVALID_RESPONSE`：HTTP/JSON/Schema/响应大小不合法。
- `PLANNING_CONTEXT_LIMIT_EXCEEDED`：Issue、证据或构造 Prompt 超过显式限制。
- `PLANNING_EVIDENCE_INVALID`：输出引用未知 rank/path/symbol 或包含禁止的 Patch 数据。
- `WORKSPACE_INCONSISTENT`：Snapshot/Index/Retrieval/HEAD/clean 不一致。
- `PLANNING_FAILED`：未分类内部错误的受限摘要。

数据库不可用继续抛出 `DatabaseUnavailableError`，不得把存储故障伪装成普通模型失败。

## 测试策略

- AC1 → 图结构单测断言固定节点与边，并用 Fake Provider 验证顺序。`[test_strategy: tdd]`
- AC2 → Service/Store 集成测试覆盖四类 SHA 与 dirty Worktree 不一致。`[test_strategy: regression]`
- AC3 → Pydantic Schema、Prompt 和证据 rank 校验单测。`[test_strategy: tdd]`
- AC4 → 计划路径/Symbol/步骤/测试策略边界与 Patch 拒绝单测。`[test_strategy: tdd]`
- AC5 → PostgreSQL migration、原子保存、回滚与唯一约束集成测试。`[test_strategy: tdd]`
- AC6 → 前端 fetch/hook/component 测试与真实浏览器刷新/停止轮询。`[test_strategy: smoke]`
- AC7 → Provider 超时/非法响应和 Pipeline failure mapping 测试。`[test_strategy: tdd]`
- AC8 → 历史 `retrieved` 状态与页面加载回归。`[test_strategy: regression]`
- AC9 → Planning 开关两条 Pipeline 分支测试。`[test_strategy: tdd]`
- AC10 → loopback 配置、Prompt Injection fixture、HEAD/clean 前后核对。`[test_strategy: regression]`
- AC11 → 真实 Ollama MarkupSafe 评测和人工浏览器证据。`[test_strategy: smoke]`
