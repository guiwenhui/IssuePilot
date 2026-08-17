# IssuePilot

IssuePilot 是一个面向小型 Python 公开仓库的需求交付学习项目。M0–M5 已通过产品验收。用户可提交公开 GitHub 仓库和 Issue，后台在受控目录完成浅克隆、Python AST 解析、三路混合检索和本地结构化规划，页面展示固定 Commit、真实代码证据、需求分析和待审批实施计划。

M5 使用无 Checkpoint 的固定 LangGraph 四节点图，将 M4 Top 10 证据交给本机 Ollama `qwen3:8b`；输出经严格 Schema 和证据引用校验后原子保存。代码证据不会离开本机，也不会导入、执行或修改仓库代码。审批与恢复仍属于 M6。

## 当前架构

- Next.js App Router + TypeScript：页面渲染、表单交互与状态轮询。
- FastAPI + Pydantic：API 契约、输入校验与结构化错误。
- SQLAlchemy Async + asyncpg：任务业务逻辑与 PostgreSQL 访问。
- Alembic：显式管理数据库 Schema；应用启动时不会自动建表。
- PostgreSQL 16 + pgvector：任务业务状态、代码 Chunk、向量和检索证据的权威来源。
- 进程内单消费者队列：在 HTTP 请求外串行执行 M2 克隆；服务重启不会恢复内存队列。
- Git CLI + 隔离工作区：以固定参数浅克隆，工作区是真实仓库文件的权威来源。
- 隔离 Python Parser：以固定 argv 子进程运行标准库 AST，限制文件、字节、条目和时间。
- PostgreSQL 代码索引：保存与固定 Commit 绑定的文件、符号、Import 和测试结构。
- 本机 Ollama：使用 `qwen3-embedding:0.6b` 生成 1024 维文档与查询向量。
- Retrieval Service：生成安全 Chunk，执行 FTS/Symbol/Vector exact scan、RRF 和规则重排。
- LangGraph Planning：固定执行 retrieve/analyze/plan/persist，无工具调用、循环或 Checkpoint。
- 本机 Chat Model：`qwen3:8b` 以 Structured Output 生成需求分析和实施计划。

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

5. 复制环境变量并执行 migration：

   ```bash
   cp .env.example .env
   cd backend
   ../.venv/bin/alembic -c alembic.ini upgrade head
   ```

   首次运行数据库集成测试时，另建隔离测试库并升级它；测试清理绝不会连接开发业务库：

   ```bash
   docker exec issuepilot-postgres createdb -U issuepilot issuepilot_test
   env DATABASE_URL=postgresql+asyncpg://issuepilot:issuepilot@localhost:54329/issuepilot_test \
     ../.venv/bin/alembic -c alembic.ini upgrade head
   ```

6. 在 `backend` 目录启动 API：

   ```bash
   ../.venv/bin/uvicorn app.main:app --reload --port 8000
   ```

7. 另开终端，在项目根目录启动网页：

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
- `GET /api/v1/tasks/{task_id}/planning`：核对 Snapshot、Index、Retrieval Run 与真实工作区后返回本地模型生成的结构化分析和 v1 待审批计划。
- 错误使用统一 `{ "error": { "code", "message", "details" } }` 结构；输入错误为 `422`，任务不存在为 `404`，快照未就绪/不一致为 `409`，数据库不可用为 `503`。

系统继续只接受无凭据、无端口、无查询参数的 `https://github.com/{owner}/{repo}`。默认工作区为 `/tmp/issuepilot-workspaces`，所有本地模型 URL 必须是无凭据的 loopback HTTP。仓库内容不会被导入、执行或初始化 Submodule/LFS；M5 仅把受限检索证据发送给同机 Ollama。

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
../.venv/bin/alembic -c alembic.ini current
```

数据库集成测试需要本地 PostgreSQL 容器和已迁移的 `issuepilot_test`。可通过 `TEST_DATABASE_URL` 覆盖测试连接；测试不会使用 `DATABASE_URL` 中的开发业务库。项目不会自动 Commit、Push 或创建 PR。
