# IssuePilot 调用链

## 文档说明

以下是调用链及其逐步落地计划。M1–M7 已验收。Patch 生成与 pytest 执行均已落地为独立、可审计授权。

## 1. 请求链

首次落地：M1。

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Next.js TaskForm
    participant API as FastAPI POST /api/v1/tasks
    participant Service as TaskService.create_task()
    participant DB as PostgreSQL tasks

    User->>Web: 输入公开仓库 URL 与 Issue
    Web->>API: 提交 JSON 请求
    API->>API: Pydantic 校验
    alt 输入合法
        API->>Service: 创建任务命令
        Service->>DB: INSERT task(status=created)
        DB-->>Service: task_id
        Service-->>API: Task DTO
        API-->>Web: 201 + task_id + status
        loop M1 轮询
            Web->>API: GET /api/v1/tasks/{task_id}
            API->>Service: 查询任务
            Service->>DB: SELECT task
            DB-->>Service: 当前任务记录
            Service-->>API: Task DTO
            API-->>Web: 当前任务状态
        end
    else 输入非法
        API-->>Web: 422 + 结构化校验错误
    end
```

输入是仓库 URL 和 Issue；输出是可持久化查询的 `task_id`、状态和错误契约。M1 不克隆仓库，也不启动 Agent。后续若加入 SSE，仍由 FastAPI 推送事件，数据库继续作为权威状态来源。

### M1 已实现契约

1. 首页 Client Component 将 `{ repository_url, issue }` 发送到 `POST /api/v1/tasks`。
2. Pydantic 拒绝额外字段、非 HTTPS/无主机/带凭据的 URL、空 Issue 和超长输入；合法 URL 不在 M1 发起网络访问。
3. Task Service 开启异步数据库事务并插入 `status=created` 的记录；成功返回 `201`、`Location` 和任务 DTO。
4. 前端导航到 `/tasks/{task_id}`，立即请求 `GET /api/v1/tasks/{task_id}`，之后在前一次请求结束 3 秒后再调度下一次，避免重叠请求。
5. 每次查询都由 FastAPI 重新读取 PostgreSQL，并返回 `Cache-Control: no-store`；页面刷新不依赖浏览器缓存恢复状态。

错误统一为 `{ error: { code, message, details } }`：字段或路径参数不合法返回 `422`，任务不存在返回 `404`，数据库连接/事务不可用返回 `503`，未分类异常返回 `500`。详情页遇到 `4xx` 会展示错误并停止轮询；网络错误或 `5xx` 会展示错误并继续有限频率轮询，以便服务恢复后自动重新同步。

## 2. 仓库获取链

首次落地：M2。

```mermaid
sequenceDiagram
    participant Web as Next.js
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Queue as In-process Queue
    participant Worker as Repository Service
    participant Git as Git CLI
    participant FS as Isolated Workspace

    Web->>API: POST /api/v1/tasks
    API->>API: 严格校验 github.com URL
    API->>DB: INSERT created → queued
    API->>Queue: enqueue(task_id)
    API-->>Web: 201 queued
    Queue->>Worker: 单消费者领取任务
    Worker->>DB: queued → cloning
    Worker->>Git: ls-remote（无凭据、无重定向）
    Worker->>Git: depth=1 clone 到 staging
    Git->>FS: 写入受控任务目录
    Worker->>Git: rev-parse + ls-tree + status
    Worker->>FS: 体积、数量、深度与路径校验
    Worker->>FS: staging 原子移动到正式目录
    Worker->>DB: 保存 Snapshot + cloning → cloned
    Web->>API: GET task（轮询）
    API->>DB: SELECT status
    API-->>Web: cloned
    Web->>API: GET repository/tree
    API->>DB: SELECT Snapshot
    API->>FS: 核对目录、HEAD 和 clean 状态
    API-->>Web: Commit + 受限文件树
```

M2 把“请求错误”和“任务业务失败”分开：不安全 URL 在任何 Git 调用前返回 `422` 且不建任务；远程仓库不存在、私有、超时或超限时，任务本身已经存在，因此 GET Task 返回 `200 + status=failed + failure`。数据库/工作区/SHA 不一致时 Tree API 返回 `409 WORKSPACE_INCONSISTENT`，不会用数据库 Manifest 掩盖真实文件缺失。

页面在 `created/queued/cloning` 继续非重叠轮询，在 `cloned/failed` 停止；`cloned` 只读取一次 Tree API。Tree API 的网络错误或 `5xx` 可继续低频重试，永久 `4xx` 停止。

## 3. Python 结构化链

首次落地：M3。

```mermaid
sequenceDiagram
    participant Queue as Repository Queue
    participant Service as Code Index Service
    participant DB as PostgreSQL
    participant Git as Git/Workspace
    participant Parser as Isolated Python Parser
    participant Web as Next.js

    Queue->>DB: Snapshot + cloning → indexing
    Queue->>Service: index_task(task_id)
    Service->>DB: 读取 Task + Repository Snapshot
    Service->>Git: 核对目录、HEAD SHA、clean、tracked entries
    Service->>Parser: 固定 argv + 受限请求文件
    Parser->>Git: 只读 tracked 普通 .py
    Parser->>Parser: ast.parse + Visitor
    Parser-->>Service: 文件、符号、Import、测试、文件级警告
    Service->>DB: 单事务保存结构 + indexing → retrieving（M4 新任务）
    Web->>DB: 经 FastAPI 轮询任务
    Web->>Service: GET code/structure
    Service->>Git: 再次核对真实工作区
    Service-->>Web: Commit + 受限结构预览
```

M3 历史任务在 `indexed/failed` 停止；M4 新任务由索引事务直接进入 `retrieving`。历史 M2 `cloned` 和 M3 `indexed` 仍是终态。解析错误分两级：单文件编码/语法问题作为索引警告；没有可解析 Python、超时、超限、Parser 协议错误或工作区不一致使任务进入 `failed`。任何情况下都不 Import 或执行仓库代码。

## 4. 检索链

结构化代码首次落地：M3；完整混合检索首次落地：M4。

```mermaid
sequenceDiagram
    participant Queue as Repository Queue
    participant Service as Retrieval Service
    participant Git as Git/Workspace
    participant Ollama as Local Ollama
    participant DB as PostgreSQL + pgvector
    participant Web as Next.js

    Queue->>Service: retrieve_task(task_id)
    Service->>DB: 读取 Task/Snapshot/Index/File/Symbol
    Service->>Git: 核对 Snapshot SHA、Index SHA、HEAD、clean、tracked hash
    Service->>Service: Symbol/模块边界 Chunk + 资源限制
    Service->>Service: 按 path/行号/content hash 去重，保留更具体 Symbol
    Service->>Ollama: POST /api/embed（文档批次 + Issue 查询）
    Ollama-->>Service: 1024 维有限数向量
    Service->>DB: 保存 Chunk + FTS + vector(1024)
    Service->>DB: Keyword / Symbol / exact cosine 各取 50
    Service->>Service: RRF v1 + rules v1，确定性 Top 10
    Service->>DB: 原子保存 Run/Result + retrieving → retrieved
    Web->>DB: 经 FastAPI 读取 task/repository/code/retrieval
    Service->>Git: 读取 Retrieval 前再次核对真实工作区
    Service-->>Web: Commit、模型、path、symbol、行号、snippet、通道排名与分数
```

M4 新任务在 `retrieving` 继续轮询，在 `retrieved/failed` 停止；历史 `cloned/indexed` 保持终态且不自动补排。正常输出必须带固定 Commit、文件路径、符号、行号、代码片段和每路排名，不能只返回模型总结。Embedding 不可用、响应非法、资源超限或检索持久化逻辑错误会保存稳定失败码；数据库连接错误保持基础设施错误语义。Repository Worker 通过独立 Session 和单条活跃状态条件更新收敛失败任务，避免页面轮询一个已经退出的任务且不覆盖并发形成的终态；数据库可用性错误保留 `DATABASE_UNAVAILABLE`，其余未分类异常使用 `REPOSITORY_PIPELINE_FAILED`。已形成的 Tree 和 Code Structure 仍可读取。

## 5. 本地规划链

分析与规划首次落地：M5。

```mermaid
sequenceDiagram
    participant Pipeline as Repository Pipeline
    participant Store as Planning Store
    participant Git as Git/Workspace
    participant Graph as LangGraph
    participant Ollama as Local qwen3:8b
    participant DB as PostgreSQL
    participant Web as Next.js

    Pipeline->>DB: Retrieval 成功 → analyzing
    Pipeline->>Graph: ainvoke(task_id)
    Graph->>Store: retrieve_code
    Store->>DB: 读取 Snapshot/Index/Retrieval/Top 10
    Store->>Git: 核对 HEAD SHA 与 clean
    Graph->>Graph: 裁剪证据 + 稳定 SHA256
    Graph->>Ollama: analyze_requirement（JSON Schema, think=false）
    Ollama-->>Graph: RequirementAnalysis JSON
    Graph->>Ollama: create_plan（JSON Schema, think=false）
    Ollama-->>Graph: ImplementationPlan JSON
    Graph->>Graph: 校验 rank/path/symbol 与禁止内容
    Graph->>Store: persist_plan
    Store->>DB: 锁定任务并复核 Commit/Run
    Store->>DB: 原子保存三表 + waiting_approval
    Web->>DB: 经 FastAPI 读取四份证据
    Web-->>Web: 展示计划；无审批按钮
```

M5 图固定为 `START → retrieve_code → analyze_requirement → create_plan → persist_plan → END`，不包含 Checkpoint、Interrupt、工具、循环或文件写入。模型失败、输出非法、证据越界或工作区不一致会保存稳定 failure code；数据库不可用仍返回基础设施错误。`waiting_approval` 只是业务状态和页面提示。

## 6. 人工审批与恢复链

首次落地：M6。

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Next.js Approval UI
    participant API as Decision API
    participant DB as PostgreSQL Business Tables
    participant Queue as Planning Queue
    participant CP as PostgreSQL Checkpointer
    participant Graph as LangGraph v2
    participant Repo as Git Worktree
    participant Model as 本机 qwen3:8b

    User->>Web: approve / request_changes / reject
    Web->>API: POST decision + plan_version + idempotency_key
    API->>DB: 锁 Task 与 Plan；保存 pending intent
    API-->>Web: 202 decision_pending
    API->>Queue: enqueue decision_id
    Queue->>CP: 读取暂停 Checkpoint
    Queue->>DB: 核对 Run/Plan/Evidence hash
    Queue->>Repo: 核对 HEAD 与 clean
    alt approve 或 reject
        Queue->>Graph: Command(resume=decision)
        Graph->>DB: 原子应用决定
    else request_changes
        Queue->>Graph: Command(resume=feedback)
        Graph->>Model: 原 Issue + Analysis + Plan + 同一 Evidence
        Model-->>Graph: Structured Plan draft
        Graph->>DB: 保存 vN+1 并 supersede vN
        Graph->>CP: 再次 Interrupt
    else 任一事实不一致
        Queue->>DB: decision failed + recovery_blocked
    end
```

相同幂等键的串行或并发重试只产生一个决定。业务表保存用户可查询的决定和计划版本；Checkpoint 只保存节点执行位置。M5 计划没有 Checkpoint 时，首次决定会在完成全部一致性检查后 bootstrap 到审批暂停点。批准只得到 `approved`，不会自动进入 Patch。

## 7. 隔离 Patch 与白名单测试链

首次落地：M7。

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Next.js M7 UI
    participant API as Implementation API
    participant DB as PostgreSQL Business Tables
    participant Queue as Implementation Queue
    participant CP as PostgreSQL Checkpointer
    participant Graph as Implementation Graph
    participant Source as 来源仓库
    participant WT as Implementation Worktree
    participant Model as 本机 qwen3:8b
    participant Runner as 固定 Docker pytest Runner

    User->>Web: 授权生成 Patch
    Web->>API: POST implementation + plan_version + idempotency_key
    API->>DB: 锁定 approved Task/Plan，保存 pending Run
    API-->>Web: 202 implementation_pending
    API->>Queue: enqueue implementation_run_id
    Queue->>CP: 读取独立 implementation thread
    Queue->>DB: 核对 Plan/Run/Evidence/Commit
    Queue->>Source: 核对 HEAD、clean、tracked hash
    Graph->>WT: 从固定 Commit 创建隔离 Worktree
    Graph->>Model: Issue + approved Plan + 允许文件及原 hash
    Model-->>Graph: FileReplacement JSON
    Graph->>WT: 路径/hash/类型/资源校验后原子替换
    Graph->>WT: Git 生成并审计规范 Unified Diff
    Graph->>DB: 保存 Patch、SHA256、manifest、统计
    Graph->>CP: Interrupt(test approval)
    Web->>API: GET implementation
    API->>Source: 再核对来源 HEAD/clean
    API->>WT: 重生成 Diff 并比对 Patch hash
    API-->>Web: patch_ready + 精确 Diff
    User->>Web: 查看 Patch 后授权 pytest
    Web->>API: POST tests + expected_patch_sha256 + idempotency_key
    API->>DB: 保存 pending Test Run
    API->>Queue: enqueue test_run_id
    Queue->>Graph: Command(resume=test approval)
    Graph->>Runner: 固定 argv + 只读 Worktree
    Runner-->>Graph: exit/timeout/duration/bounded output/hash
    Graph->>DB: 原子保存 tested 或 test_failed
    Web->>API: GET implementation
    API-->>Web: 展示真实测试证据并停止轮询
```

两个 `POST` 都使用 UUID 幂等键，但授权对象不同：第一次确认可在隔离 Worktree 写文件，第二次确认可执行不可信仓库测试代码。第二次还必须携带页面所见 Patch 的 SHA256，Patch 被改变或 Worktree 无法复核时返回 `409`，不会执行测试。

Implementation Graph 与 M6 Planning Graph 使用不同 Checkpoint thread。业务表回答“用户授权了什么、Patch/Test 证据是什么”，Checkpoint 回答“图暂停在哪个节点”，来源仓库与 Implementation Worktree 回答“磁盘上的真实代码是什么”。启动恢复同时核对 Graph/Prompt/provider/model/thread、业务状态/计划版本和精确 Worktree。合法的早期节点可幂等继续；数据库已保存 Patch 而 Checkpoint 仍停在 `apply_patch` 的提交窗口会先复核真实 Diff，再幂等推进至 Interrupt。其他节点错位直接 `recovery_blocked`。已经开始运行却没有完成证据的测试会先确认遗留容器被终止，再安全阻断，不自动重跑。

Runner 只执行固定 `python -m pytest -q -p no:cacheprovider`，使用固定镜像 digest、无网络、非 root、只读 Worktree、cap-drop/no-new-privileges、CPU/内存/PID/宿主机与容器内双层超时/输出限制。它只接受本机 Unix Docker socket，不安装目标仓库依赖，不接受用户或模型命令，也不回退宿主机。缺依赖、pytest 失败和超时都作为 `test_failed` 证据保存；`tested` 也只表示 exit code 为 0，M8 才进行 Reviewer、质量 Gate 与有限修复。

## 8. 失败链

基本错误契约从 M1 开始；跨节点 Checkpoint 恢复已在 M6 落地，M7 增加 Patch/Test 副作用核对；有限修复循环仍在 M8 落地。

```mermaid
flowchart TD
    Error["节点或工具异常"] --> Classify["分类：输入 / 暂时性 / 代码 / 测试 / 权限 / 安全"]
    Classify --> Retryable{"允许重试？"}
    Retryable -->|"否"| Persist["保存错误证据与最后成功节点"]
    Retryable -->|"是"| Limit{"是否低于该类型上限？"}
    Limit -->|"是"| Retrying["状态设为 retrying\n记录 attempt 与原因"]
    Retrying --> Resume["从安全 Checkpoint 恢复"]
    Resume --> Verify["验证结果"]
    Verify -->|"成功"| Continue["返回原执行阶段"]
    Verify -->|"再次失败"| Classify
    Limit -->|"否"| Persist
    Persist --> Failed["failed"]
    Failed --> Human["人工查看证据并决定恢复、修改或取消"]
```

恢复不是还原模型当时的思考，而是读取持久化状态、文件、事件与最后成功节点，再安全地继续。对可能产生副作用的步骤，恢复前必须检查幂等性并在需要时再次请求批准。

## 状态与证据约定

每次状态变化至少记录：

- `task_id`
- 原状态与新状态
- 当前节点或阶段
- 事件时间
- 尝试次数
- 错误类型与摘要（如有）
- 最后成功节点（如有）
- 测试命令、退出码与输出摘要（测试阶段）

页面展示的“成功”必须来自已持久化的执行证据，不能只来自 LLM 文本。
