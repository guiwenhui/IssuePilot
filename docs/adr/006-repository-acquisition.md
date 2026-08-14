# ADR-006：M2 仓库获取与后台执行

- Status: Accepted
- Date: 2026-08-14

## Context

仓库克隆是第一个耗时、访问外部网络并写文件的步骤。同步放在 HTTP 请求内会阻塞并放大超时；直接为每个请求创建 BackgroundTask 缺少并发控制；提前引入 Redis/RQ 又会增加尚未被真实需求证明的基础设施。

## Decision

M2 使用 FastAPI lifespan 管理的进程内 `asyncio.Queue`，容量 20、单消费者。POST 创建 PostgreSQL 任务后入队，Worker 使用独立异步 Session 执行 `queued → cloning → cloned/failed`。成功结果保存固定 Commit Snapshot，并通过独立 Tree API 返回。

服务重启不恢复内存队列，多实例也不会共享队列。M2 明确接受该限制，不用伪恢复掩盖真实缺口；后续依据重启丢失、并发和排队指标决定是否引入持久队列。

## Alternatives

### HTTP 请求内同步克隆

实现简单，但长请求容易超时，无法展示排队/克隆状态，也不能统一控制并发。

### FastAPI BackgroundTasks

响应可快速返回，但每个请求可独立启动任务，没有明确容量和单消费者背压。

### Redis + RQ/Celery

支持持久队列和多 Worker，但 M2 尚无部署与恢复数据证明该复杂度必要。

## Consequences

- M2 调用链简单、可测试且不新增依赖。
- 单消费者限制磁盘和网络并发，任务高峰会排队。
- 进程重启可能留下 `queued/cloning` 状态或孤立目录；恢复必须在后续同时核对 PostgreSQL、Checkpoint（落地后）和真实工作区。
- Queue 是可替换边界，升级持久队列时不改变前端或 Git/Workspace 职责。
