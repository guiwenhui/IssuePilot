# ADR-004：业务与向量存储

- Status: Accepted
- Date: 2026-08-13

## Context

IssuePilot 需要保存任务状态、事件、恢复信息和代码索引元数据，并在 M4 支持向量检索。MVP 数据规模较小，若同时引入业务数据库与专用向量数据库，会增加运维和一致性成本。

## Decision

M1 使用 PostgreSQL 保存任务业务数据。M4 在同一数据库引入 pgvector，保存代码 Embedding 并支持向量召回。PostgreSQL 是任务状态的权威来源；LangGraph Checkpoint 和 Git 工作区分别保存工作流状态与仓库文件，不替代任务业务表。

索引策略在获得真实评测数据后选择；不在 M0 预设 HNSW 或 IVFFlat 一定优于另一方。

M1 使用 SQLAlchemy 2 异步 ORM、asyncpg 和显式 Alembic migration。首个 `tasks` 表保存 UUID、仓库 URL、Issue 文本、`created` 状态以及创建/更新时间。应用启动不自动创建或升级表，Schema 变更必须通过可审查、可回退的 migration 执行。

## Alternatives

### SQLite

优点是零服务、原型简单。缺点是与后续并发 Worker、部署和 pgvector 学习目标不一致。

### Qdrant、Milvus 或 Weaviate

优点是提供更专业的向量检索能力。缺点是 MVP 需要额外部署、同步业务元数据并维护更多组件。

### ChromaDB

优点是本地原型快。缺点是不适合作为完整业务数据的权威存储，并会形成两套持久化边界。

## Consequences

- MVP 可在同一数据库管理业务数据、索引元数据和向量，降低运维成本。
- PostgreSQL Schema 需要清楚区分任务、事件、Checkpoint 元数据和代码索引。
- 超大规模向量检索能力不是本阶段目标；规模增长后可基于指标迁移。
- M1 不需要 pgvector，避免把未使用能力提前写入实现。
- 数据库不可用时事务回滚，API 返回结构化 `503`，不会伪造一个只存在于浏览器内的任务。
