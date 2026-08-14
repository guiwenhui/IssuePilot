# Design: M1

> 文档版本：2
>
> [SPEC-DELTA v1] 原因：浏览器验收发现永久 404 仍持续轮询。此为澄清性变更，不改变范围；4xx 停止轮询，网络错误与 5xx 继续重试。

## 架构决策

| 决策 | 理由 | 备选方案 |
|---|---|---|
| 浏览器直接调用 FastAPI | 最直接验证既定前后端边界 | Next.js BFF/Rewrite；可在部署约束出现后评估 |
| FastAPI + Pydantic 拥有输入与响应契约 | 业务规则只有一个权威实现并生成 OpenAPI | Server Actions 直连数据库；违反 ADR-001 |
| SQLAlchemy 异步 Session 按请求创建 | 与异步 API 匹配且避免跨请求共享 Session | 同步 ORM；实现简单但会阻塞异步处理线程 |
| Alembic 显式 migration | Schema 可审计、可升级、可回滚 | 启动时 `create_all()`；不可作为正式变更流程 |
| PostgreSQL 保存业务状态 | 与 ADR-004 和后续 pgvector 演进一致 | SQLite；无法验证目标持久化边界 |
| 固定间隔、非重叠轮询 | M1 简单且可测 | SSE/WebSocket；本阶段没有真实事件流 |

## 数据模型

`tasks` 表：

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | UUID | 主键，由应用生成 |
| `repository_url` | VARCHAR(2048) | 非空 |
| `issue_text` | TEXT | 非空 |
| `status` | VARCHAR(32) | 非空，M1 仅写入 `created` |
| `created_at` | TIMESTAMPTZ | 数据库生成，非空 |
| `updated_at` | TIMESTAMPTZ | 数据库生成，非空 |

M1 不创建事件、Checkpoint、Worktree、Patch 或测试证据字段。

## API 契约

### `POST /api/v1/tasks`

请求字段：`repository_url`、`issue`。禁止额外字段。URL 只做 HTTPS 结构校验，不访问网络。

成功：`201`，返回 `task_id`、`repository_url`、`issue`、`status`、`created_at`、`updated_at`。

### `GET /api/v1/tasks/{task_id}`

成功：`200`，返回同一 Task DTO，并设置禁止缓存响应头。

### 错误格式

统一返回 `{ "error": { "code": string, "message": string, "details": array } }`。

- `422 VALIDATION_ERROR`
- `404 TASK_NOT_FOUND`
- `503 DATABASE_UNAVAILABLE`
- `500 INTERNAL_ERROR`

## 接口边界

调用方向固定为：Next.js Client Component → FastAPI Router → Task Service → SQLAlchemy Session → PostgreSQL。前端不直接访问数据库或修改业务状态；Router 不直接编写 SQL；ORM 模型不直接作为外部响应。

## 状态与流程

M1 唯一写入状态为 `created`。创建成功后状态不会自动推进。轮询只读取 PostgreSQL 中的当前状态，为后续里程碑状态转换保留契约。

## 错误契约

- 输入错误在数据库写入前返回 `422`。
- 合法 UUID 无记录返回 `404`。
- SQLAlchemy/驱动连接类故障映射为 `503`，事务回滚。
- 未分类错误记录服务端日志并返回 `500`，不泄露堆栈或连接信息。
- 浏览器网络错误只更新连接状态，保留最后成功任务数据。
- 浏览器收到明确 4xx 后停止轮询；网络错误与 5xx 保持固定间隔重试。

## 关键文件

| 文件 | 打算怎么改 |
|---|---|
| `app/page.tsx` | 保留品牌内容并加入真实任务入口 |
| `app/tasks/[taskId]/page.tsx` | 提供可刷新、可分享的任务详情路由 |
| `components/task-create-form.tsx` | 处理提交、字段错误和跳转 |
| `components/task-status-panel.tsx` | 查询、非重叠轮询和连接错误 |
| `lib/api/tasks.ts` | 集中 API 调用与错误解析 |
| `backend/app/main.py` | 组装 FastAPI、CORS 和异常处理 |
| `backend/app/api/routes/tasks.py` | 创建与查询端点 |
| `backend/app/services/task_service.py` | 创建、事务提交与查询业务逻辑 |
| `backend/app/models/task.py` | `tasks` ORM 模型 |
| `backend/app/schemas/task.py` | 请求、响应、状态和 URL 校验 |
| `backend/migrations/` | 初始 tasks migration |

## 复用点

- 复用现有 `app/layout.tsx` 元数据和 `app/globals.css` 品牌变量。
- 复用现有首页的 M0/M1 状态表达，将静态边界升级为真实入口。
- 复用 M0 `docs/call-chains.md` 的请求链作为实现验收依据。
