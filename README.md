# IssuePilot

IssuePilot 是一个面向小型 Python 公开仓库的需求交付学习项目。M0、M1、M2、M3、M4 已通过产品验收。用户可提交公开 GitHub 仓库和 Issue，后台在受控目录完成浅克隆、Python AST 解析和三路混合检索，页面展示 PostgreSQL 中的业务状态、固定 Commit、真实文件树、结构化代码和排名证据。

M4 使用 PostgreSQL FTS、M3 Symbol 和本机 Ollama Embedding 召回代码，经 RRF 与确定性规则重排；不调用 OpenAI、不启动 Agent，也不导入、执行或修改仓库代码。后续能力及边界见 [`docs/product-scope.md`](docs/product-scope.md)。

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

## 本地运行

以下命令均从项目根目录开始。需要 Node.js、Python 3.9+、Git CLI、Docker 与 Ollama。

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

4. 启动 Ollama 并下载本地 Embedding 模型：

   ```bash
   ollama serve
   ollama pull qwen3-embedding:0.6b
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
- 错误使用统一 `{ "error": { "code", "message", "details" } }` 结构；输入错误为 `422`，任务不存在为 `404`，快照未就绪/不一致为 `409`，数据库不可用为 `503`。

M4 继续只接受无凭据、无端口、无查询参数的 `https://github.com/{owner}/{repo}`。默认工作区为 `/tmp/issuepilot-workspaces`，克隆、AST、Chunk 和 Embedding 资源限制见 [`.env.example`](.env.example)。仓库内容不会被导入、执行或初始化 Submodule/LFS；只有 tracked 普通 `.py` 文件进入 Parser 和本机 Embedding。

## 验证命令

```bash
npm run lint
npm run typecheck
npm run test:frontend
npm run build

cd backend
../.venv/bin/python -m pytest --cov=app --cov-report=term-missing
RUN_OLLAMA_LIVE=1 ../.venv/bin/python -m pytest tests/test_retrieval_evaluation.py -m ollama -s
../.venv/bin/alembic -c alembic.ini current
```

数据库集成测试需要本地 PostgreSQL 容器和已迁移的 `issuepilot_test`。可通过 `TEST_DATABASE_URL` 覆盖测试连接；测试不会使用 `DATABASE_URL` 中的开发业务库。项目不会自动 Commit、Push 或创建 PR。
