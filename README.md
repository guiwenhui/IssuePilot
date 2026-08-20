# IssuePilot

IssuePilot 是一个面向小型 Python 公开仓库的需求交付学习项目。M0–M7 已通过产品验收。用户可提交公开 GitHub 仓库和 Issue，后台完成隔离克隆、Python AST、三路混合检索、本地结构化规划、人工审批、隔离 Patch 和白名单测试。

M7 不把 M6 的计划批准直接当作文件写入授权。用户需先明确生成 Patch，系统才会从固定 Commit 创建独立 Git Worktree，让本机 `qwen3:8b` 输出受限的完整文件替换，并由 Git 生成规范 Unified Diff。用户查看 Diff 后还要再次授权，固定 Docker Runner 才会以无网络、非 root、只读仓库挂载方式执行 `python -m pytest -q -p no:cacheprovider`。测试失败也是有效证据，不会回退到宿主机或在线安装依赖。

## 当前架构

- Next.js App Router + TypeScript：页面渲染、表单交互与状态轮询。
- FastAPI + Pydantic：API 契约、输入校验与结构化错误。
- SQLAlchemy Async + asyncpg：任务业务逻辑与 PostgreSQL 访问。
- Alembic：显式管理数据库 Schema；应用启动时不会自动建表。
- PostgreSQL 16 + pgvector：任务业务状态、代码 Chunk、向量和检索证据的权威来源。
- 进程内单消费者队列：串行执行克隆、M6 决定和 M7 实现；已持久化的 pending 决定与实现请求可在启动时重排，克隆队列仍不持久化。
- Git CLI + 隔离工作区：以固定参数浅克隆；M7 从固定 Commit 创建独立 Worktree，来源仓库始终只读且保持 clean。
- 隔离 Python Parser：以固定 argv 子进程运行标准库 AST，限制文件、字节、条目和时间。
- PostgreSQL 代码索引：保存与固定 Commit 绑定的文件、符号、Import 和测试结构。
- 本机 Ollama：使用 `qwen3-embedding:0.6b` 生成 1024 维文档与查询向量。
- Retrieval Service：生成并确定性去重安全 Chunk，执行 FTS/Symbol/Vector exact scan、RRF 和规则重排。
- LangGraph Planning：v2 在 persist 后 Interrupt；三种决定经 Command 恢复，计划修改有界循环。
- LangGraph Implementation：独立 Checkpoint thread 生成并持久化 Patch，在测试授权点 Interrupt，再由 Command 恢复测试。
- PostgreSQL Checkpointer：只保存节点执行状态，位于独立 schema；任务、计划和决定仍由业务表负责。
- 本机 Chat Model：`qwen3:8b` 以 Structured Output 生成需求分析、实施计划和 M7 File Replacement；规划与实现使用独立输出预算。
- 固定 Docker Test Runner：只运行服务端白名单 pytest argv；固定镜像、无网络、非 root、只读 Worktree、资源/超时/输出限制，不允许宿主机降级。

## 本地运行

以下命令均从项目根目录开始。需要 Node.js、Python 3.11+（本项目已验证 3.13）、Git CLI、Docker 与 Ollama。

1. 安装前端依赖：

   ```bash
   npm install
   ```

2. 创建 Python 虚拟环境并安装后端依赖：

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install './backend[dev]'
   ```

3. 首次创建本地 PostgreSQL 容器：

   ```bash
   docker run --name issuepilot-postgres \
     -e POSTGRES_USER=issuepilot \
     -e POSTGRES_PASSWORD=issuepilot \
     -e POSTGRES_DB=issuepilot \
     -p 127.0.0.1:54329:5432 \
     -v issuepilot-postgres-data:/var/lib/postgresql/data \
     --health-cmd='pg_isready -U issuepilot -d issuepilot' \
     --health-interval=2s --health-timeout=2s --health-retries=15 \
     -d pgvector/pgvector:pg16
   ```

   容器已存在时使用 `docker start issuepilot-postgres`。旧 `postgres:16` 镜像不包含 M4 所需的 `vector` 扩展；迁移前应先备份，并改用 `pgvector/pgvector:pg16` 或单独的 pgvector 测试容器。Docker Compose 属于 M10。

4. 启动 Ollama 并下载本地 Embedding 与规划模型：

   ```bash
   ollama serve
   ollama pull qwen3-embedding:0.6b
   ollama pull qwen3:8b
   ```

5. 构建 M7 固定 pytest Runner 镜像：

   ```bash
   docker build -t issuepilot-pytest-runner:m7 backend/runner
   ```

   Runner 镜像只包含固定 Python 与 pytest，不安装目标仓库依赖。容器内监督进程具有独立硬超时，服务重启也会按确定性容器名清理并确认遗留容器已消失。项目缺少依赖时会得到真实 `test_failed` 证据，而不是隐式联网安装或回退宿主机。

6. 复制环境变量并执行 migration：

   ```bash
   cp .env.example .env
   cd backend
   ../.venv/bin/alembic -c alembic.ini upgrade head
   ../.venv/bin/python -m app.checkpoints.setup
   ```

   首次运行数据库集成测试时，另建隔离测试库并升级它；测试清理绝不会连接开发业务库：

   ```bash
   docker exec issuepilot-postgres createdb -U issuepilot issuepilot_test
   env DATABASE_URL=postgresql+asyncpg://issuepilot:issuepilot@localhost:54329/issuepilot_test \
     ../.venv/bin/alembic -c alembic.ini upgrade head
   env DATABASE_URL=postgresql+asyncpg://issuepilot:issuepilot@localhost:54329/issuepilot_test \
     ../.venv/bin/python -m app.checkpoints.setup
   ```

7. 在 `backend` 目录启动 API：

   ```bash
   ../.venv/bin/uvicorn app.main:app --reload --port 8000
   ```

8. 另开终端，在项目根目录启动网页：

   ```bash
   npm run dev
   ```

浏览器访问 `http://localhost:3000`，FastAPI OpenAPI 文档位于 `http://localhost:8000/docs`。

## 当前 API

- `POST /api/v1/tasks`：创建任务并放入仓库队列，成功返回 `201`、`Location` 与任务 DTO。
- `GET /api/v1/tasks/{task_id}`：查询已持久化任务，响应禁止缓存。
- `GET /api/v1/tasks/{task_id}/repository/tree`：在核对工作区与 Commit 后返回仓库快照。
- `GET /api/v1/tasks/{task_id}/code/structure`：在核对索引、Snapshot 与真实工作区后返回受限 Python 结构预览。
- `GET /api/v1/tasks/{task_id}/retrieval`：在再次核对 Commit 与真实工作区后返回查询、模型、候选数、代码片段、通道排名和融合分数。
- `GET /api/v1/tasks/{task_id}/planning`：返回当前计划版本、审批历史和已验证分析。
- `POST /api/v1/tasks/{task_id}/planning/decisions`：以计划版本和幂等键接收 `approve/request_changes/reject`，返回 `202` pending decision。
- `POST /api/v1/tasks/{task_id}/implementation`：以批准计划版本和幂等键请求生成隔离 Patch，返回 `202`。
- `GET /api/v1/tasks/{task_id}/implementation`：重新核对来源仓库和实现 Worktree 后，返回 Run、Patch 与测试证据。
- `POST /api/v1/tasks/{task_id}/implementation/tests`：以预期 Patch SHA256 和幂等键明确授权固定 pytest，返回 `202`。
- 错误使用统一 `{ "error": { "code", "message", "details" } }` 结构；输入错误为 `422`，任务不存在为 `404`，快照未就绪/不一致为 `409`，数据库不可用为 `503`。

系统继续只接受无凭据、无端口、无查询参数的 `https://github.com/{owner}/{repo}`。所有模型 URL 必须是无凭据 loopback HTTP。M7 只改隔离 Worktree 内、同时出现在实施步骤和测试目标中的既有 tracked UTF-8 `.py` 文件；不新建、删除、重命名或 Commit。代码、Issue 和计划只发送给同机 Ollama。pytest 会执行不可信仓库代码，因此只能通过本机 Unix socket 进入固定容器，不接受 TCP/SSH 远程 Docker，也不进入宿主机。

## 验证命令

```bash
npm run lint
npm run typecheck
npm run test:frontend
npm run build

cd backend
../.venv/bin/python -m pytest --cov=app --cov-report=term-missing
RUN_OLLAMA_LIVE=1 ../.venv/bin/python -m pytest tests/test_retrieval_evaluation.py -m ollama -s
RUN_OLLAMA_LIVE=1 ../.venv/bin/python -m pytest tests/test_planning_evaluation.py -m ollama -s
RUN_OLLAMA_LIVE=1 ../.venv/bin/python -m pytest tests/test_implementation_evaluation.py -m ollama -s
RUN_DOCKER_LIVE=1 ../.venv/bin/python -m pytest tests/test_test_runner_docker.py -m docker -s
../.venv/bin/alembic -c alembic.ini current
```

数据库集成测试需要本地 PostgreSQL 容器和已迁移的 `issuepilot_test`。可通过 `TEST_DATABASE_URL` 覆盖测试连接；测试不会使用 `DATABASE_URL` 中的开发业务库。真实 Docker 测试需先构建固定 Runner 镜像。M7 的 `tested` 只表示该次 pytest exit code 为 0，不代表 M8 审查或整个任务已完成。项目不会自动 Commit、Push 或创建 PR。
