# ADR-004：业务与向量存储

- Status: Accepted
- Date: 2026-08-13

## Context

IssuePilot 需要保存任务状态、事件、恢复信息和代码索引元数据，并在 M4 支持向量检索。MVP 数据规模较小，若同时引入业务数据库与专用向量数据库，会增加运维和一致性成本。

## Decision

M1 使用 PostgreSQL 保存任务业务数据。M4 在同一数据库引入 pgvector，保存代码 Embedding 并支持向量召回。PostgreSQL 是任务状态的权威来源；LangGraph Checkpoint 和 Git 工作区分别保存工作流状态与仓库文件，不替代任务业务表。

索引策略在获得真实评测数据后选择；不在 M0 预设 HNSW 或 IVFFlat 一定优于另一方。

M1 使用 SQLAlchemy 2 异步 ORM、asyncpg 和显式 Alembic migration。首个 `tasks` 表保存 UUID、仓库 URL、Issue 文本、`created` 状态以及创建/更新时间。应用启动不自动创建或升级表，Schema 变更必须通过可审查、可回退的 migration 执行。

M2 在 `tasks` 增加失败码/消息和状态索引，并新增一对一 `repository_snapshots`，保存 canonical URL、Commit SHA、计数和受限 JSONB Manifest。Snapshot 是可查询证据，Git 隔离目录仍是文件事实来源；Tree API 必须核对两者。

M3 新增 `code_indexes`、`code_files`、`code_symbols`、`code_imports` 规范化表。它们保存与 Repository Snapshot Commit 绑定的 Python 结构，便于 M4 按路径、符号和 Import 查询；不提前保存 Embedding。读取结构前仍核对真实工作区。

M4 启用 `vector` 扩展并新增 `code_chunks`、`retrieval_runs`、`retrieval_results`。Chunk 保存 `TSVECTOR` 和固定 `vector(1024)`；Run 保存 Commit、Issue hash、Provider/模型、算法版本与候选计数；Result 保存三路 rank/score、RRF 和最终重排分数。小仓库使用 exact cosine scan，不建立 HNSW/IVFFlat；数据规模和延迟出现证据后再评估 ANN。

M5 新增 `planning_runs`、`requirement_analyses`、`implementation_plans`。Run 对 Task 与 Retrieval Run 各自唯一，保存 Commit、Graph/Prompt/模型版本和 Evidence hash；Analysis 与 proposed v1 Plan 使用受限 JSONB 保存已验证结构。LangGraph Checkpoint 仍未引入，不能把这些业务产物当成 M6 的节点执行状态。

M6 新增 `planning_decisions`、Plan 自引用版本关系和最多一个 proposed Plan 的条件唯一索引。Checkpoint 使用官方 PostgreSQL Saver，内部表位于独立 `issuepilot_checkpoint` schema，并通过显式 `python -m app.checkpoints.setup` 初始化；应用启动只验证，不建表。业务 migration 的 downgrade 不自动删除 Checkpoint schema，避免误删恢复证据。

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
- Checkpoint 与业务事务无法成为一个原子事务；pending intent 是可重放的恢复桥梁。
- 超大规模向量检索能力不是本阶段目标；规模增长后可基于指标迁移。
- M4 migration 需要实际包含 `vector` 扩展的 PostgreSQL 镜像；普通 `postgres:16` 不能伪装兼容。
- 数据库连接不可用时事务回滚，API 返回结构化 `503`，不会伪造一个只存在于浏览器内的任务。
- 唯一约束等持久化逻辑错误与连接故障分开分类；检索任务保存稳定失败证据，Repository Worker 未分类异常也不能让业务表永久停在假活跃状态。
