# Proposal: M2

> doc_version: 2

> [SPEC-DELTA v1] 原因：数据库集成测试必须使用独立 `issuepilot_test`，禁止清理或修改开发环境中的浏览器验收任务。

## 背景与目标

M1 已完成任务创建、PostgreSQL 持久化和页面轮询。M2 要让任务真正读取一个受支持的公开仓库：在网络访问前执行安全 URL 校验，通过简单后台队列把仓库浅克隆到受控隔离目录，固定 HEAD Commit，并向页面展示真实文件树和失败证据。

## 范围

### 范围内

- 首版只接受 `https://github.com/{owner}/{repo}` 公开仓库 URL。
- 进程内单消费者队列，状态流为 `created → queued → cloning → cloned`，失败进入 `failed`。
- 使用固定参数和隔离环境调用 Git CLI，不使用 Shell，不读取凭据，不跟随重定向，不初始化 Submodule，不下载 Git LFS 内容。
- 浅克隆到基于任务 UUID 推导的隔离工作区，执行超时、体积、文件数量和目录深度限制。
- PostgreSQL 保存克隆状态、失败证据、Commit SHA 和文件树快照；文件系统保存真实仓库。
- 新增仓库文件树 API，并在任务页面展示 Commit 和文件清单。

### 范围外

- GitHub 以外的 Git Host、私有仓库认证和用户凭据。
- Redis、RQ、Celery、多进程 Worker、任务取消、手动重试和服务重启恢复。
- Submodule 初始化、Git LFS 内容下载、完整历史克隆。
- Python AST、Embedding、检索、LangGraph、Agent、Patch、测试执行、Commit、Push 或 PR。

## 验收标准

- **AC1**：给定合法的公开 GitHub 仓库，当用户创建任务，则 API 快速返回任务编号，后台状态按合法顺序到达 `cloned`。
- **AC2**：给定非 HTTPS、非 GitHub、带凭据/端口/查询/Fragment 或不安全路径，当用户创建任务，则在网络访问前返回 `422 VALIDATION_ERROR` 且不创建任务。
- **AC3**：给定不存在、私有或无法访问的仓库，当后台验证远程仓库，则任务进入 `failed` 并持久化稳定失败码和安全消息。
- **AC4**：给定 Git 超时、工作区超限、文件数超限或目录深度超限，当执行克隆，则终止本任务、清理其 staging，并保存对应失败证据。
- **AC5**：给定成功克隆，当页面读取仓库树，则返回固定 Commit SHA、文件数量、字节数与受限文件条目；不暴露 `.git`、本机绝对路径或跟随符号链接。
- **AC6**：给定 PostgreSQL 快照、工作区目录和 HEAD SHA 不一致，当读取文件树，则返回 `409 WORKSPACE_INCONSISTENT` 而不是虚假成功。
- **AC7**：给定任务到达 `cloned` 或 `failed`，当页面收到终态，则停止轮询，并分别展示仓库树或失败证据；刷新后仍从 API 恢复。
- **AC8**：给定 M2 migration，当在空测试数据库执行 `upgrade → downgrade → upgrade`，则 Schema 可重复演进且 M1 回归保持通过。

## 影响模块

- `backend/app/core` —— Git Host、工作区和资源限制配置。
- `backend/app/models` / `backend/migrations` —— 任务失败字段与仓库快照。
- `backend/app/services` —— URL、Git、工作区和仓库克隆编排。
- `backend/app/workers` —— 进程内单消费者队列及生命周期。
- `backend/app/api` / `backend/app/schemas` —— M2 状态、失败和文件树契约。
- `lib` / `components` / `app` —— 终态轮询、失败与文件树展示。
- `docs` —— M2 真实架构、调用链、安全决策和术语。

## 测试策略

- AC1 → Service/Queue/API 状态流测试 + 批准仓库浏览器验收 `[test_strategy: tdd]`
- AC2 → URL 安全矩阵单元测试，验证 Git Adapter 未被调用 `[test_strategy: tdd]`
- AC3 → Git 返回码/认证失败映射及持久化测试 `[test_strategy: tdd]`
- AC4 → 超时、体积、文件数、深度与安全清理测试 `[test_strategy: tdd]`
- AC5 → 临时 Git 仓库 Manifest 测试 + API/浏览器树展示 `[test_strategy: tdd]`
- AC6 → 缺目录、错误 SHA 和脏工作区回归测试 `[test_strategy: tdd]`
- AC7 → 前端终态调度和组件浏览器验收 `[test_strategy: tdd]`
- AC8 → Alembic upgrade/downgrade/upgrade + M1/M2 全量回归 `[test_strategy: smoke]`
