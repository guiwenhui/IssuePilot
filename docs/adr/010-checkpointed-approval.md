# ADR-010：Checkpoint 化人工审批

- Status: Accepted
- Date: 2026-08-17

## Context

M5 能生成并保存 proposed 计划，但 `waiting_approval` 只是展示终态。M6 需要接收批准、修改或拒绝，并在服务重启、HTTP 重试和并发双击下避免重复决定。单独信任数据库状态或 Checkpoint 都可能基于旧代码、旧计划或错误节点继续。

## Decision

使用官方 PostgreSQL LangGraph Checkpointer 和 `Interrupt/Command`。业务表与 Checkpoint 分离：`tasks/implementation_plans/planning_decisions` 保存用户可查询和约束的业务事实；专用 schema 的 Checkpoint 保存节点 channel state。

决定请求携带计划版本和 UUID 幂等键。服务在行锁内先保存 pending intent，再交给有界单消费者。恢复前核对 Graph/Prompt、Planning Run、Evidence hash、Snapshot/Index/Retrieval Commit、Worktree HEAD 与 clean。M5 无 Checkpoint 计划可在核对后 bootstrap；其他不一致进入 `recovery_blocked`。

request_changes 复用原 Issue、不可变 Analysis、当前 Plan 和同一 Evidence，通过本机 qwen3:8b 只生成 vN+1 Plan。approve/reject 不调用模型。M6 的 `approved` 不授权写文件或执行测试。

## Alternatives

### HTTP 请求内同步恢复

实现较少，但模型修订会长时间占用请求；在业务提交后进程崩溃会留下难以判断的结果。

### 只保存 Checkpoint

能恢复节点，却不适合作为可查询、可约束、可审计的用户决定与计划版本来源。

### Redis/RQ 持久队列

可跨实例共享调度，但 M6 当前并发有限；PostgreSQL pending intent 已能在重启后重排，先不增加基础设施。

## Consequences

- 串行和并发重复请求只产生一个决定。
- Checkpoint 与业务事务不是 exactly-once；所有业务副作用必须幂等。
- 应用启动只验证 Checkpoint schema，部署必须显式运行 setup。
- 恢复宁可阻塞也不基于不一致事实猜测下一节点。
- 关闭 `APPROVAL_WORKFLOW_ENABLED` 可退回 M5 只读计划；业务和 Checkpoint 表保留供审计。
