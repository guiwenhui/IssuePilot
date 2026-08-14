# IssuePilot

IssuePilot 是一个面向小型 Python 公开仓库的需求交付学习项目。M1 已于 2026-08-14 通过产品验收：用户可从 Next.js 页面提交仓库 HTTPS 地址和 Issue，FastAPI 完成校验并把任务保存到 PostgreSQL，详情页随后轮询数据库中的权威状态。

M1 只建立“创建—保存—查询”的最小闭环，不克隆仓库、不启动 Agent，也不执行代码。后续能力及边界见 [`docs/product-scope.md`](docs/product-scope.md)。

## 当前架构

- Next.js App Router + TypeScript：页面渲染、表单交互与状态轮询。
- FastAPI + Pydantic：API 契约、输入校验与结构化错误。
- SQLAlchemy Async + asyncpg：任务业务逻辑与 PostgreSQL 访问。
- Alembic：显式管理数据库 Schema；应用启动时不会自动建表。
- PostgreSQL 16：任务业务状态的权威来源。

## 本地运行

以下命令均从项目根目录开始。需要 Node.js、Python 3.9+ 与 Docker。

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
     -d postgres:16
   ```

   容器已存在时使用 `docker start issuepilot-postgres`。Docker Compose 属于 M10，不在 M1 提前引入。

4. 复制环境变量并执行 migration：

   ```bash
   cp .env.example .env
   cd backend
   ../.venv/bin/alembic -c alembic.ini upgrade head
   ```

5. 在 `backend` 目录启动 API：

   ```bash
   ../.venv/bin/uvicorn app.main:app --reload --port 8000
   ```

6. 另开终端，在项目根目录启动网页：

   ```bash
   npm run dev
   ```

浏览器访问 `http://localhost:3000`，FastAPI OpenAPI 文档位于 `http://localhost:8000/docs`。

## M1 API

- `POST /api/v1/tasks`：创建任务，成功返回 `201`、`Location` 与任务 DTO。
- `GET /api/v1/tasks/{task_id}`：查询已持久化任务，响应禁止缓存。
- 错误使用统一 `{ "error": { "code", "message", "details" } }` 结构；输入错误为 `422`，任务不存在为 `404`，数据库不可用为 `503`。

## 验证命令

```bash
npm run lint
npm run typecheck
npm run test:frontend
npm run build

cd backend
../.venv/bin/python -m pytest --cov=app --cov-report=term-missing
../.venv/bin/alembic -c alembic.ini current
```

数据库集成测试需要本地 PostgreSQL 容器处于运行状态。项目不会自动 Commit、Push 或创建 PR。
