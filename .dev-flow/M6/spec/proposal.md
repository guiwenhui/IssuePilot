# Proposal: M6

> status: approved for implementation
> approved_at: 2026-08-17
> accepted_at: 2026-08-17
> doc_version: 2
>
> spec_deltas: `[{stage: "implementation", reason: "真实仓库验收暴露父级窗口与方法块重合导致唯一键冲突，且后台异常未收敛任务状态", classification: "范围性（用户已批准 mini-Gate）", at: "2026-08-17"}]`

> [SPEC-DELTA v2] 原因: 真实 IssuePilot 仓库检索产生相同位置与内容的父级/方法 Chunk，唯一键冲突又被误判为数据库不可用，使任务永久停在 `retrieving`。M6 验收补充确定性 Chunk 去重、持久化错误分类、后台未分类异常收敛和卡死状态恢复，不改变 M7 边界。

## 背景与目标

M5 已将固定 Commit、检索证据、需求分析和 proposed v1 计划原子保存，但 `waiting_approval` 仍是只读终态。M6 要把人工决定变成可审计、可幂等、可跨进程恢复的工作流：用户可以批准、要求修改或拒绝计划；LangGraph 在 Interrupt 处暂停并以 PostgreSQL Checkpoint 恢复；任何恢复都先核对 Checkpoint、业务数据库和真实 Worktree。

成功标准是：审批不能被绕过，重复请求不能重复生效，计划修改形成新版本，服务重启后能从最后安全节点继续，且整个里程碑仍不修改目标仓库文件。

## 范围

### 范围内

- 为 M6 Planning Graph 配置 PostgreSQL LangGraph Checkpointer 和人工 Interrupt。
- 新增批准、要求修改、拒绝三种决定及完整审计历史。
- 要求修改时只修订实施计划，不改变原 Issue 或 M5 Requirement Analysis；本机 `qwen3:8b` 使用原证据和用户反馈生成下一版本。
- 使用持久化 pending decision 作为恢复意图，以进程内单消费者执行器处理；服务启动时重新排入尚未应用的 M6 决定。
- 对新 M6 任务恢复 Graph；对 M5 历史 `waiting_approval` 从已保存计划安全初始化审批 Checkpoint；对无计划的遗留 `analyzing` 在一致性核对后从固定 M4 证据重新规划。
- 前端展示审批控件、计划版本和审批历史，并在活跃状态继续轮询。
- 新增业务 migration、显式 Checkpointer Schema 初始化命令、自动化测试、真实 PostgreSQL/本地模型/浏览器验收和文档更新。

### 范围外

- 生成或应用 Patch、写目标仓库、运行目标仓库测试（M7）。
- Reviewer、自动修复环和失败重试策略（M8）。
- Git Commit、Push、PR、GitHub 写权限和用户身份绑定。
- 多用户账号、RBAC、远程公开部署审批；M6 仍是本机单操作员 MVP。
- Redis/RQ、多个 Worker 共享消费和严格 exactly-once；M6 提供业务副作用的幂等重放。
- 修改 Requirement Analysis 或 Issue 范围；范围改变应创建新任务。

## 验收标准

- **AC1 — Interrupt**：给定 M6 新任务生成合法计划，当 Planning Graph 到达审批节点时，则保存 PostgreSQL Checkpoint、任务进入 `waiting_approval`，且没有审批输入不能进入后续节点。
- **AC2 — 批准**：给定 proposed 计划和匹配版本，当用户提交唯一幂等键的 approve 决定时，则先保存 pending 决定，再恢复 Graph，最终计划和任务进入 `approved`，Worktree 不变化。
- **AC3 — 修改**：给定 proposed 计划，当用户提交 `request_changes` 和非空反馈时，则本机模型基于同一 Evidence 生成并校验 vN+1，vN 标记 superseded，新版本再次进入 `waiting_approval`。
- **AC4 — 拒绝**：给定 proposed 计划，当用户提交 reject 和原因时，则决定、计划和任务原子进入 `rejected`，后续不能再审批。
- **AC5 — 幂等与并发**：给定相同 `(task_id, idempotency_key)` 或两个针对同一旧版本的并发请求，则相同键返回原决定，不同键只有一个能接受，另一个返回 `409`。
- **AC6 — 三方一致性**：给定 Snapshot/Index/Retrieval/Planning Commit、Evidence hash、Worktree HEAD 或 clean 状态任一不一致，当审批或恢复发生时，则不推进 Graph，返回或保存稳定 `409` 恢复诊断。
- **AC7 — 跨进程恢复**：给定 `analyzing`、`decision_pending` 或 `revising` 任务和安全 Checkpoint，当服务重新启动时，则从最后安全节点恢复，不重复业务副作用。
- **AC8 — 历史兼容**：给定 M5 已保存计划但没有 Checkpoint 的 `waiting_approval`，当首次提交决定时，则从数据库计划初始化审批 Checkpoint，不重新执行 M5 模型调用。
- **AC9 — API/页面**：给定 `waiting_approval` 页面，当用户批准、要求修改或拒绝时，则页面发送版本化决定，活跃期轮询，终态显示计划版本、决定历史和明确状态；刷新从 API 恢复。
- **AC10 — 错误契约**：非法 UUID/字段返回 `422`，任务不存在返回 `404`，状态/版本/工作区/Checkpoint 冲突返回 `409`，数据库或 Checkpointer 不可用返回 `503`。
- **AC11 — 功能开关与回滚**：关闭 `APPROVAL_WORKFLOW_ENABLED` 时，系统保持 M5 只读 `waiting_approval` 行为，不接受决定、不初始化 Checkpoint。
- **AC12 — 里程碑边界**：M6 的批准只把计划标记为 approved；没有文件写入、Patch、Shell、目标仓库测试、Commit 或 PR。

## 影响模块

- `backend/app/agents/` —— M6 Graph、Interrupt、条件路由和修订 Prompt。
- `backend/app/checkpoints/` —— PostgreSQL Saver 生命周期、配置和显式 setup。
- `backend/app/models/`、`backend/migrations/` —— 审批记录、计划版本关系和任务状态。
- `backend/app/services/`、`backend/app/workers/` —— 决定事务、恢复协调、持久 pending 工作列表。
- `backend/app/api/`、`backend/app/schemas/` —— 决定端点、响应和错误契约。
- `components/`、`lib/`、`app/` —— 审批交互、版本历史、状态轮询和样式。
- `docs/`、`.codex/project-config.md`、`README.md` —— M6 真实架构、调用链、ADR 和术语。

## 数据模型

- `planning_decisions`：`id`、`task_id`、`run_id`、`plan_id`、`plan_version`、`action`、`comment`、`idempotency_key`、`status`、`failure_code/message`、`created_at/applied_at`；唯一约束 `(task_id, idempotency_key)`。
- `implementation_plans` 新增 `supersedes_plan_id`、`revision_feedback`、`decided_at`；status 支持 `proposed/approved/rejected/superseded`。
- TaskStatus 新增 `decision_pending/revising/approved/rejected/recovery_blocked`。
- LangGraph Checkpointer 使用同一 PostgreSQL 的独立 Checkpoint Schema；其内部表由显式 setup 命令管理，不在应用启动时偷偷建表。

## API 契约

### POST `/api/v1/tasks/{task_id}/planning/decisions`

请求：`action`、`expected_plan_version`、`idempotency_key`、`comment`。`request_changes/reject` 必须有 comment，approve 可选。成功返回 `202` 和决定 id/status；重复幂等键返回同一决定。

### GET `/api/v1/tasks/{task_id}/planning`

保持 M5 字段兼容，扩展当前计划状态、`supersedes_plan_id`、`revision_feedback` 和有界决定历史。

## 接口边界

- Next.js 只提交和展示人工决定，不判断合法状态。
- FastAPI/Pydantic 校验字段，Approval Service 决定状态与版本合法性。
- PostgreSQL 业务表是用户状态和审计权威；Checkpoint 只负责 Graph 执行位置。
- Graph 只能通过 Adapter 读取证据、保存版本和应用决定；LLM 没有文件、Shell 或审批权限。
- Worktree 始终只读核对；M6 任何节点不得写入目标仓库。

## 状态与流程

`analyzing → waiting_approval → decision_pending → approved|rejected|revising`；`revising → waiting_approval`。一致性或恢复失败进入 `recovery_blocked`，未分类生成失败进入 `failed`。`approved/rejected` 是 M6 终态。

## 错误契约

- `APPROVAL_NOT_READY`、`PLAN_VERSION_CONFLICT`、`DECISION_ALREADY_APPLIED`、`CHECKPOINT_MISSING`、`CHECKPOINT_INCONSISTENT`、`WORKSPACE_INCONSISTENT` → `409`。
- `CHECKPOINTER_UNAVAILABLE`、`DATABASE_UNAVAILABLE` → `503`。
- 修订模型继续复用 M5 `LLM_UNAVAILABLE/INVALID_RESPONSE/PLANNING_EVIDENCE_INVALID`，失败不得覆盖最后一个可审查计划。

## 测试策略

- AC1 → Graph 拓扑、Interrupt、无输入不可越过和真实 Postgres Saver 测试。`[test_strategy: tdd]`
- AC2/AC4 → 批准/拒绝事务、Worktree 不变和 API/浏览器测试。`[test_strategy: tdd]`
- AC3 → 修订 Prompt、Evidence Validator、版本链和真实本地模型冻结案例。`[test_strategy: tdd]`
- AC5 → 重复键、旧版本和并发数据库集成测试。`[test_strategy: tdd]`
- AC6/AC7/AC8 → 三方不一致、重建 Runtime、pending 重排和 M5 bootstrap 集成测试。`[test_strategy: regression]`
- AC9 → TypeScript API、轮询、交互组件和浏览器刷新测试。`[test_strategy: tdd]`
- AC10/AC11 → 错误 handler、配置开关和历史 M5 回归。`[test_strategy: regression]`
- AC12 → HEAD/clean/文件摘要前后比较和静态边界扫描。`[test_strategy: smoke]`
