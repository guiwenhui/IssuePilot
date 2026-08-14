# ADR-002：任务状态更新方式

- Status: Accepted
- Date: 2026-08-13

## Context

任务创建后，浏览器需要知道当前状态。轮询、SSE 和 WebSocket 都可用于状态更新，但 M1 的目标是先验证浏览器、API、Service 和数据库的最小调用链，而不是实现实时日志系统。

## Decision

M1 使用 HTTP 轮询查询任务状态。前端提交任务后获得 `task_id`，随后调用任务查询 API；FastAPI 从 PostgreSQL 读取权威状态。

轮询间隔固定为 3 秒，并在上一次请求结束后才调度下一次，避免慢请求造成并发堆积。`4xx` 表示当前请求本身不能通过重试修复，因此展示错误并停止；网络错误与 `5xx` 可能是暂时故障，因此保持同一低频轮询。组件卸载时取消在途请求并清理定时器。

出现持续事件流展示需求后，再评估升级为 SSE。即使采用 SSE，任务最终状态仍以 PostgreSQL 为准。

M2 增加业务终态规则：`created`、`queued`、`cloning` 继续轮询，`cloned`、`failed` 停止轮询。Tree 使用独立 API，只在 `cloned` 后读取，避免每次状态请求重复传输大清单。

M3 新任务在 Snapshot 生效时直接进入 `indexing`，完成后进入 `indexed`。前端把 `created/queued/cloning/indexing` 视为活跃，把历史 `cloned`、`indexed`、`failed` 视为终态；`indexed` 后分别读取 Tree 与 Code Structure API。这样避免短暂 `cloned` 竞态，也不会让升级前 M2 任务永久轮询。

## Alternatives

### SSE

优点是服务器可通过单向长连接及时推送进度，适合 Agent 事件流。缺点是连接管理、断线续传和代理配置会增加 M1 调试成本。

### WebSocket

优点是支持全双工实时通信。缺点是本项目早期没有持续双向通信需求，协议和连接状态管理偏重。

### 长轮询

优点是比固定轮询更及时。缺点是服务端请求保持与超时处理更复杂，学习收益不如先完成普通轮询再升级 SSE 清晰。

## Consequences

- M1 实现和测试路径简单，便于理解 HTTP 与持久化。
- 状态更新会有轮询间隔带来的延迟和重复请求。
- API 应允许合理的轮询频率，并为后续事件模型保留扩展空间。
- 暂时性故障恢复后页面可自动重新同步；永久客户端错误不会形成无意义请求风暴。
- 切换 SSE 时不改变 Next.js 与 FastAPI 的业务职责边界。
