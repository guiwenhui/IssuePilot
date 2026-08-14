# Proposal: M3

> doc_version: 2
>
> spec_deltas: `[{stage: T6, reason: "避免历史 M2 cloned 任务永久轮询", classification: "澄清性", at: "2026-08-14"}]`

## 背景与目标

M2 已把公开 GitHub 仓库固定到受控工作区和 Commit，但系统目前只能展示文件树，不能解释 Python 源码由哪些模块、类、函数、Import 和测试结构组成。M3 在不执行仓库代码、不引入向量检索或 Agent 的前提下，把 Git tracked Python 源码解析为可查询、可核对的结构化索引。

成功标准是：新任务在克隆完成后自动进入 AST 解析阶段，解析结果与 Repository Snapshot 的 Commit 一致并持久化到 PostgreSQL，页面能展示结构摘要和来源行号，错误和资源超限具有稳定证据。

## 范围

### 范围内

- 使用 Python 标准库 AST 提取 tracked `.py` 文件、类、函数、方法、Import 和测试结构。
- 使用独立、固定 argv 的 Python 子进程解析不可信源码，不导入或执行仓库模块。
- 保存 Commit、解析器/Python 版本、文件、符号、Import、测试标记和文件级解析错误。
- 启用 `cloned → indexing → indexed` 状态；索引失败进入 `failed`。
- 新增只读 Code Structure API 和前端结构化预览。
- 对 Python 文件数、单文件/总字节、提取条目和解析时间设置服务端上限。
- 解析前复核 Repository Snapshot、工作区目录、HEAD SHA、clean 状态和 tracked entries。
- 更新 M2 已验收状态、架构、调用链、ADR 和术语表。

### 范围外

- 关键词检索、Embedding、pgvector、融合、重排和 Recall@K（M4）。
- LangGraph、LLM 需求分析和计划生成（M5）。
- Checkpoint、Interrupt、恢复、持久队列或服务重启自动续跑（M6 或后续评估）。
- Patch、Worktree、pytest 执行、Commit、Push 或 PR。
- Python Import 解析、第三方依赖加载、仓库代码执行或多语言解析。
- 为升级前已经停在 `cloned` 的历史任务自动补排索引任务。

## 验收标准

- **AC1**：给定一个成功克隆的小型 Python 仓库，当后台处理继续时，则任务依次进入 `indexing` 和 `indexed`，并保存与 Repository Snapshot 相同的 Commit SHA。
- **AC2**：给定包含同步、异步、嵌套类/函数/方法的 Python 文件，当解析完成时，则保存名称、限定名、父符号、类型、起止行、签名和装饰器。
- **AC3**：给定绝对、相对、别名和 `from` Import，当解析完成时，则保存 module、imported name、alias、relative level、作用域和行号，但不执行 Import。
- **AC4**：给定 `tests/`、`test_*.py`、`*_test.py`、`Test*`、`test_*` 和 fixture，当解析完成时，则文件和符号带有可查询的测试标记。
- **AC5**：给定带 PEP 263 编码声明或单文件语法错误的仓库，当解析完成时，则合法文件按声明读取，错误文件保存受限错误摘要，其他文件结果仍可用。
- **AC6**：给定未跟踪文件、符号链接、Submodule、路径逃逸或资源超限输入，当索引时，则只读取安全 tracked 普通 `.py` 文件，危险或超限任务失败且不执行仓库代码。
- **AC7**：给定 Snapshot、HEAD SHA、clean 状态任一不一致，当开始索引或读取结果时，则返回/保存 `WORKSPACE_INCONSISTENT`，不返回旧索引冒充当前结果。
- **AC8**：给定索引尚未就绪、任务不存在、UUID 非法或数据库不可用，当调用 Code Structure API 时，则分别返回稳定的 `409`、`404`、`422`、`503` 错误契约。
- **AC9**：给定索引成功的任务，当刷新详情页时，则页面重新从 FastAPI 读取 PostgreSQL 和工作区证据，停止轮询并展示 Commit、数量、文件、符号、Import、测试和解析警告。
- **AC10**：给定索引失败但 Repository Snapshot 已存在的任务，当读取 Tree API 时，则仍可核对并查看克隆成功的文件树。

## 影响模块

- `backend/app/parsers` —— 新增 AST 提取与隔离子进程协议。
- `backend/app/models`、`backend/migrations` —— 新增代码索引数据模型和可回退 migration。
- `backend/app/services` —— 新增索引服务并扩展工作区一致性检查。
- `backend/app/workers`、`backend/app/main.py` —— 在同一单消费者流程中串联克隆与索引。
- `backend/app/api`、`backend/app/schemas` —— 新增 Code Structure 只读契约与错误映射。
- `lib`、`components`、`app` —— 支持 M3 状态、读取和展示结构结果。
- `docs`、`README.md`、`.codex/project-config.md` —— 更新真实里程碑状态和架构决策。

## 数据模型

- `code_indexes`：以 `task_id` 为主键和外键，保存 `commit_sha`、`parser_version`、`python_version`、各类计数和 `indexed_at`。
- `code_files`：保存任务、path、module、source SHA-256、行/字节数、测试文件标记、parse status 和受限错误摘要；`(task_id, path)` 唯一。
- `code_symbols`：保存 file、可选 parent、kind、name、qualified name、起止行、signature、decorators、async/test/fixture 标记。
- `code_imports`：保存 file、kind、module、imported name、alias、relative level、作用域和行号。
- 所有子表通过 `ON DELETE CASCADE` 跟随任务/索引删除；索引产物和 `indexed` 状态在同一事务提交。
- Migration downgrade 先把 `indexing/indexed` 退回 `cloned`，再按依赖顺序删除 M3 表。

## API 契约

- `GET /api/v1/tasks/{task_id}/code/structure`
  - `200`：返回任务、Commit、解析器版本、汇总计数、文件级警告和最多 2,000 个确定排序的结构预览。
  - `404 TASK_NOT_FOUND`：任务不存在。
  - `409 CODE_INDEX_NOT_READY`：索引尚未形成。
  - `409 WORKSPACE_INCONSISTENT`：索引/Repository Snapshot/真实工作区不一致。
  - `422 VALIDATION_ERROR`：UUID 或请求字段非法。
  - `503 DATABASE_UNAVAILABLE`：业务数据库不可用。
- `GET /api/v1/tasks/{task_id}/repository/tree` 改为以 Snapshot 存在和工作区核对为准，不再要求任务状态恰好为 `cloned`。
- `GET /api/v1/tasks/{task_id}` 增加 `indexing/indexed` 枚举，不把索引结构塞入轮询 DTO。

## 接口边界

- Queue 只调度一个 task processor；processor 先调用 Repository Service，再调用 Code Index Service。
- Repository Service 仍独占 Git 克隆和 Repository Snapshot；Code Index Service 不克隆、不改工作区。
- Parser 子进程只接收服务端生成的工作区路径与限制，输出结构化 JSON；它不访问数据库、不改变任务状态。
- Code Index Service 负责一致性复核、解析器调用、数据库事务和业务失败映射。
- Next.js 只在终态读取 Code Structure API，不复制 AST 或状态转换规则。

## 状态与流程

```text
created → queued → cloning → indexing → indexed
                     ↘ failed     ↘ failed
```

- `created/queued/cloning/indexing` 为 M3 活跃状态；`cloned/indexed/failed` 为前端终态。
- > [SPEC-DELTA v1] 原因: 升级前的 M2 `cloned` 不会自动补排，若把 `cloned` 设为活跃状态会永久轮询。M3 新流水线在 Repository Snapshot 落库的同一事务直接从 `cloning` 进入 `indexing`；`cloned` 只保留为历史 M2/禁用索引时的稳定终态。
- 解析子进程崩溃、超时、超限或没有可解析 Python 文件时任务进入 `failed`，保存稳定 failure code/message。
- 单文件 `SyntaxError` 是文件级警告；只要至少一个 Python 文件可解析，允许任务进入 `indexed`。
- 进程重启仍可能留下 `queued/cloning/indexing`；M3 明确不伪装恢复。

## 错误契约

- 任务级失败：`NO_PYTHON_FILES`、`PYTHON_SOURCE_LIMIT_EXCEEDED`、`CODE_INDEX_TIMEOUT`、`CODE_INDEX_FAILED`、`WORKSPACE_INCONSISTENT`。
- 文件级失败：`syntax_error` 或 `read_error`，只保存安全、定长摘要，不保存任意异常堆栈到 API。
- 子进程使用固定 Python argv、关闭 stdin、清理环境和墙钟超时；stdout 只接受受 Schema 校验且受条目数量约束的 JSON。
- Git tracked 的 symlink/submodule 和非 `.py` 文件不交给解析器；路径必须仍在任务 repository 根目录内。

## 测试策略

- AC1 → Service/Queue 状态与单事务测试，真实临时 Git 仓库集成测试。`[test_strategy: tdd]`
- AC2 → AST Visitor 参数化单元测试。`[test_strategy: tdd]`
- AC3 → Import 变体和作用域单元测试。`[test_strategy: tdd]`
- AC4 → pytest 文件、类、函数和 fixture 识别单元测试。`[test_strategy: tdd]`
- AC5 → 编码声明、SyntaxError 和部分成功测试。`[test_strategy: tdd]`
- AC6 → symlink、tracked 类型、路径和所有资源上限测试。`[test_strategy: tdd]`
- AC7 → Snapshot/SHA/clean/source hash 不一致的 Service/API 测试。`[test_strategy: regression]`
- AC8 → FastAPI 200/404/409/422/503 契约测试。`[test_strategy: tdd]`
- AC9 → TypeScript API、轮询终态、组件和真实浏览器刷新测试。`[test_strategy: tdd]`
- AC10 → 索引失败后 Tree API 仍读取已有 Snapshot 的回归测试。`[test_strategy: regression]`
