# Design: M2

> doc_version: 2
>
> spec_deltas: `[{stage: "final-evidence", reason: "integration cleanup deleted a browser acceptance task from the development database", classification: "clarification", at: "2026-08-14"}]`

> [SPEC-DELTA v1] 原因：最终证据审计发现集成测试与开发服务器共用 `issuepilot` 数据库，清理夹具会删除真实验收任务并留下孤立工作区。测试必须使用独立 `issuepilot_test` 数据库，默认测试不得读写开发业务数据。

## 架构决策

| 决策 | 理由 | 备选方案 |
|---|---|---|
| 首版只允许 `github.com` | 严格压缩 SSRF、重定向和 Host 差异风险 | 任意公网 Git Host + DNS/IP 校验；复杂且仍有 DNS rebinding 风险 |
| 进程内单消费者 `asyncio.Queue` | HTTP 快速返回、显式背压与单并发，不新增基础设施 | 同步克隆；阻塞请求。BackgroundTasks；无统一背压。Redis/RQ；超出 M2 |
| 使用系统 Git CLI 的固定参数数组 | 行为贴近真实 Git，避免新增 Python 依赖 | GitPython/Dulwich；增加依赖且协议行为不同 |
| staging 成功后原子移动 | 页面只看到完整工作区，失败可局部清理 | 直接写正式目录；容易留下半成品 |
| PostgreSQL Snapshot + Git 工作区双重核对 | 业务状态与真实文件各有权威来源 | 只存 JSON 或只看磁盘；无法解释状态不一致 |
| 新增 `cloned` 终态和独立 Tree API | 不把克隆完成误写成整项 `completed`，避免轮询携带大树 | 使用 `indexing`；会提前宣称 M3/M4。树嵌入 Task DTO；重复传输 |

## 数据模型

### `tasks` 变更

- `failure_code VARCHAR(64) NULL`
- `failure_message TEXT NULL`
- `status` 启用 `created`、`queued`、`cloning`、`cloned`、`failed`
- 新增 `status` 普通索引。

### `repository_snapshots`

| 字段 | 类型 | 约束 |
|---|---|---|
| `task_id` | UUID | PK、FK `tasks.id`、ON DELETE CASCADE |
| `canonical_url` | VARCHAR(2048) | NOT NULL |
| `commit_sha` | VARCHAR(40) | NOT NULL |
| `file_count` | INTEGER | NOT NULL |
| `total_bytes` | BIGINT | NOT NULL |
| `tree_manifest` | JSONB | NOT NULL |
| `cloned_at` | TIMESTAMPTZ | NOT NULL、server default |

Manifest 只保存受限、排序后的 tracked entries；工作区绝对路径不进入数据库或 API。

## API 契约

### `POST /api/v1/tasks`

- 请求字段保持 `{repository_url, issue}`。
- 同步完成严格 URL 校验和数据库创建，随后放入队列；成功返回 `201`。
- 队列成功时状态为 `queued`；队列满时资源仍已创建并进入 `failed/CLONE_QUEUE_FULL`。

### `GET /api/v1/tasks/{task_id}`

在 M1 DTO 上增加 nullable `failure: {code, message}`。任务业务失败仍是 `200`，API 自身错误继续使用结构化 HTTP 错误。

### `GET /api/v1/tasks/{task_id}/repository/tree`

- `200`：`task_id`、canonical URL、Commit SHA、文件计数、总字节、`truncated` 和 entries。
- `404 TASK_NOT_FOUND`
- `409 REPOSITORY_NOT_READY`
- `409 WORKSPACE_INCONSISTENT`
- `503 DATABASE_UNAVAILABLE`

## 接口边界

调用方向固定为：Router → Task/Repository Service → Repository Queue → GitClient/WorkspaceManager → Git CLI/Filesystem；Service 通过 Session Factory 访问 PostgreSQL。Router 不拼 Git 命令，Queue 不解析 URL，GitClient 不修改业务状态，前端不读取本机路径。

系统 Git 环境清除凭据和系统/全局配置，设置非交互模式、禁用重定向、跳过 LFS smudge，并且只传固定 argv。Submodule 不初始化。

## 状态与流程

```text
created → queued → cloning → cloned
   │         │          └────→ failed
   └─────────┴───────────────→ failed
```

- Queue 只消费 `queued`，Worker 在数据库中原子认领后进入 `cloning`。
- `cloned` 与 Snapshot 在同一数据库事务中落地，但在正式目录完成原子移动之后提交。
- 页面只在非终态调度下一次轮询；`cloned` 读取一次 Tree API，`failed` 展示持久化证据。
- M2 不恢复进程重启前的内存队列；该限制保留给后续持久队列/Checkpoint 评估。

## 错误契约

| 失败码 | 来源 | 业务结果 |
|---|---|---|
| `CLONE_QUEUE_FULL` | 队列 | task `failed` |
| `REPOSITORY_UNAVAILABLE` | ls-remote/认证 | task `failed` |
| `CLONE_TIMEOUT` | Git 超时 | task `failed` |
| `CLONE_FAILED` | Git 非预期退出 | task `failed` |
| `GIT_UNAVAILABLE` | 找不到 Git | task `failed` |
| `REPOSITORY_TOO_LARGE` | 工作区体积 | task `failed` |
| `REPOSITORY_TREE_LIMIT_EXCEEDED` | 文件数/深度 | task `failed` |
| `WORKSPACE_INCONSISTENT` | 快照与目录/SHA/clean 状态不符 | Tree API 409 |

错误消息不得返回 Git stderr 中的凭据、环境变量或本机绝对路径。

## 资源限制

- `clone_timeout_seconds=60`
- `max_workspace_bytes=104857600`
- `max_tracked_files=5000`
- `max_tree_entries=2000`
- `max_tree_depth=25`
- `clone_queue_capacity=20`
- `clone_worker_count=1`

限制来自服务端配置，任务请求不能覆盖。

## 关键文件

| 文件 | 打算怎么改 |
|---|---|
| `backend/app/core/config.py` | M2 安全与资源配置、Feature Flag |
| `backend/app/models/task.py` | 失败字段和 Snapshot 关系 |
| `backend/app/models/repository_snapshot.py` | 新增快照 ORM |
| `backend/app/schemas/task.py` | M2 状态与 failure DTO |
| `backend/app/schemas/repository.py` | 文件树 DTO |
| `backend/app/services/repository_url.py` | 严格 GitHub URL 规范化 |
| `backend/app/services/git_client.py` | 非 Shell Git 子进程、超时与输出映射 |
| `backend/app/services/workspace.py` | 受控路径、staging、限制、Manifest 与清理 |
| `backend/app/services/repository_service.py` | 克隆和 Snapshot 编排 |
| `backend/app/workers/repository_queue.py` | 单消费者内存队列 |
| `backend/app/api/routes/tasks.py` | 创建后排队和 Tree endpoint |
| `backend/app/main.py` | Worker lifespan |
| `backend/migrations/versions/*_m2_repository_clone.py` | 可回退 Schema |
| `lib/api/tasks.ts` | M2 DTO 与 Tree 请求 |
| `lib/polling.ts` | 业务终态判定 |
| `components/task-status-panel.tsx` | 失败/树展示和终态停止 |
| `components/repository-tree.tsx` | Commit 与文件清单 |

## 复用点

- M1 `TaskService` 的事务和错误映射继续作为业务状态入口。
- M1 `ErrorResponse`、异常 Handler 与轮询调度继续复用。
- M1 PostgreSQL/Alembic 测试夹具扩展，不另建数据库栈。
- 现有 Task 详情页面承载 M2 状态，不新增平行页面。

## 测试策略

- URL、状态转换、错误映射、Manifest 和终态轮询使用 RED → GREEN TDD。
- GitClient 使用可注入 subprocess runner；默认测试不访问公网。
- Workspace 使用 `tmp_path` 和临时 Git 仓库验证路径、限制与一致性。
- API/Queue 使用 Fake Repository Service，避免测试时克隆外部内容。
- Alembic 和集成测试只连接独立 `issuepilot_test` 数据库，验证 upgrade/downgrade/upgrade；开发数据库仅用于浏览器验收。
- 最终 Smoke 使用已批准的 `pallets/markupsafe` 仓库并进行浏览器验证。

## 风险与回滚

- 进程重启会丢失队列；M2 明确不自动恢复。
- Git clone 在事后大小检查前仍可能消耗资源；用浅克隆、单并发与超时减轻。
- DB 与文件系统非原子；Tree API 必须验证真实目录、HEAD 和 clean 状态。
- `REPOSITORY_CLONE_ENABLED=false` 可立即回到 M1 只创建任务行为。
- 完全回滚前备份 DB/工作区，将 M2 状态归一为 `created`，再 downgrade；工作区只移动到隔离区，不执行宽泛递归删除。
