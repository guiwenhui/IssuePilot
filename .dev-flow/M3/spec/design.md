# Design: M3

> doc_version: 2
>
> spec_deltas: `[{stage: T6, reason: "消除 cloned 轮询竞态并兼容历史任务", classification: "澄清性", at: "2026-08-14"}]`

## 架构决策

| 决策 | 理由 | 备选方案 |
|---|---|---|
| 使用标准库 `ast` 和 `tokenize.open` | 无新依赖，足以提取 Python 结构并支持编码声明 | Tree-sitter/LibCST 更丰富，但提前引入依赖和多语言复杂度 |
| 在固定 argv 的独立 Python 子进程解析 | 不可信 AST 输入崩溃、超时或高 CPU 时不拖垮 FastAPI 主解释器 | 主进程/线程更简单，但隔离和阻塞边界较弱 |
| 使用规范化 PostgreSQL 表 | M4 可按 path/name/import 建索引和查询，无需扫描大 JSON | 单 JSONB 文档开发快，但查询、分页和局部更新较差 |
| 新增 `indexed` 终态 | M3 需要可轮询、可验收的稳定完成状态，且与后续 `analyzing` 清晰分开 | 长期停在 `indexing` 会造成无限轮询；退回 `cloned` 会丢失解析是否成功的信息 |
| 自动串联克隆与索引 | 新任务无需第二次用户动作，保持单消费者背压 | HTTP 按需解析会重复工作并放大请求超时 |
| 单文件语法错误允许部分成功 | 公开仓库可能含生成文件或不同 Python 版本语法，其他结构仍有价值 | 任一错误即失败会降低可用性；忽略错误又会隐藏证据 |
| Tree/Code API 以产物存在和真实一致性为准 | 总任务进入后续状态或索引失败后，已形成的仓库证据仍应可读 | 用当前 task status 判断会把 artifact readiness 与整体阶段错误耦合 |

## 关键文件

| 文件 | 打算怎么改 |
|---|---|
| `backend/app/parsers/python_ast.py` | AST Visitor、测试识别、签名/装饰器/Import 提取和限制检查 |
| `backend/app/parsers/runner.py` | 子进程入口，读取受控请求并输出受限 JSON |
| `backend/app/services/parser_client.py` | 固定 argv 异步子进程、清理环境、超时和响应 Schema 校验 |
| `backend/app/services/code_index_service.py` | 工作区一致性、状态转换、原子持久化和读取结构预览 |
| `backend/app/models/code_index.py` | index/file/symbol/import ORM 模型 |
| `backend/app/schemas/code_index.py` | Parser DTO 和 Code Structure API DTO |
| `backend/migrations/versions/20260814_03_m3_code_index.py` | 新表、索引和可回退状态清理 |
| `backend/app/main.py` | 运行时组装、克隆后解析和异常映射 |
| `backend/app/api/dependencies.py` | Code Index Service 依赖 |
| `backend/app/api/routes/tasks.py` | Code Structure GET 端点 |
| `backend/app/services/repository_service.py` | 公开复用工作区核对；Tree 改为 artifact readiness |
| `backend/app/schemas/task.py` | 增加 `indexing/indexed` 状态 |
| `lib/api/tasks.ts`、`lib/use-task-status.ts` | 新状态、Code API 和终态数据加载 |
| `components/code-structure.tsx`、`components/task-status-panel.tsx` | 展示代码结构、测试和解析警告 |
| `docs/*`、`README.md`、`.codex/project-config.md` | 更新真实状态、边界、调用链、ADR 和术语 |

## 复用点

- `GitClient.head_sha/is_clean/tracked_entries` —— 复核工作区和提供 tracked 输入。
- `WorkspaceManager.repository_path` 与 M2 路径校验 —— 只从 UUID 推导受控目录。
- `RepositorySnapshot.commit_sha` —— 代码索引的 Commit 锚点。
- `RepositoryQueue` 的单消费者和容量 —— 串联解析而不新增队列基础设施。
- `error_response` 和现有异常处理 —— 延续 `{error:{code,message,details}}`。
- `useTaskStatus` 的非重叠轮询 —— 加入 M3 终态和 artifact 读取。
- `repository-tree` 的证据展示样式 —— 保持详情页视觉层级。

## 数据模型

`code_indexes(task_id PK/FK, commit_sha, parser_version, python_version, file_count, parsed_file_count, symbol_count, import_count, test_count, parse_error_count, indexed_at)`。

`code_files(id UUID PK, task_id FK, path, module_name nullable, source_sha256, line_count, size_bytes, is_test_file, parse_status, parse_error nullable)`，唯一索引 `(task_id,path)`。

`code_symbols(id UUID PK, file_id FK, parent_id nullable self FK, kind, name, qualified_name, start_line, end_line, signature nullable, decorators JSONB, is_async, is_test, is_fixture)`；索引 `(file_id,qualified_name)` 和 `name`。

`code_imports(id UUID PK, file_id FK, kind, module nullable, imported_name nullable, alias nullable, relative_level, scope nullable, line)`；索引 `file_id` 和 `module`。

写入过程先在内存校验完整 Parser DTO，再在一个数据库事务删除同 task 旧索引、插入新索引和子项、把任务置为 `indexed`。任何数据库异常整体回滚。

## API 契约

`GET /api/v1/tasks/{task_id}/code/structure` 返回：

```json
{
  "task_id": "uuid",
  "commit_sha": "40-char sha",
  "parser_version": "py-ast-v1",
  "python_version": "3.x.y",
  "indexed_at": "timestamp",
  "counts": {
    "files": 10,
    "parsed_files": 9,
    "symbols": 40,
    "imports": 18,
    "tests": 7,
    "parse_errors": 1
  },
  "truncated": false,
  "files": []
}
```

每个 file 预览带 path/module/test/parse status/error、symbols 和 imports。文件和子条目按 path、line、qualified name 确定排序，总预览条目达到 2,000 后截断。

## 接口边界

Parser Client 只处理进程协议；Python AST 模块只处理源码到不可变 DTO；Code Index Service 才能访问任务、Snapshot、Git/Workspace 和数据库。Runner 不接收 URL、数据库凭据或任意命令。

前端不根据文件名自行判断测试结构，只显示后端解析出的标记。M4 将复用规范化表，但本里程碑不新增搜索参数或排名字段。

## 状态与流程

processor 调用 `clone_task(task_id, success_status=indexing)`，使 Snapshot 与 `indexing` 在同一事务生效，然后调用 `index_task(task_id)`。`index_task` 复核真实工作区，调用 Parser Client，最后原子提交产物与 `indexed`。

> [SPEC-DELTA v1] 原因: 若先暴露稳定 `cloned` 再提交 `indexing`，浏览器可能在两次事务之间把它误判为终态；若让 `cloned` 持续轮询，升级前且不自动补排的 M2 任务会永久轮询。新流水线因此直接持久化 `indexing`，历史 `cloned` 保持终态。

升级前已存在的 `cloned` 任务不会自动扫描入队；服务重启后的恢复仍留给后续里程碑。新任务是 M3 验收主路径。

## 错误契约

- Parser 退出非零、JSON 不合法、Schema 不合法或未知异常 → `CODE_INDEX_FAILED`。
- 超过 30 秒 → 终止子进程并保存 `CODE_INDEX_TIMEOUT`。
- Python 文件/字节/条目超过服务端配置 → `PYTHON_SOURCE_LIMIT_EXCEEDED`。
- 没有 tracked 普通 `.py` 或全部文件不可解析 → `NO_PYTHON_FILES`。
- Snapshot/目录/SHA/clean 不一致 → `WORKSPACE_INCONSISTENT`。
- 单文件编码或语法错误 → 文件级受限警告；至少一个文件成功时整体可 `indexed`。

## 资源限制

| 限制 | 默认值 |
|---|---:|
| Python 文件数 | 2,000 |
| 单个 Python 文件 | 1 MiB |
| Python 源码合计 | 20 MiB |
| Symbol + Import | 50,000 |
| Parser 墙钟时间 | 30 秒 |
| API 预览条目 | 2,000 |

这些限制仅从服务端配置读取；客户端不能提高。

## 测试策略

- Parser 纯逻辑、状态转换、持久化和 API 契约采用 TDD。
- Tree artifact readiness 使用现有失败路径先写回归测试。
- Migration、配置和文档采用 smoke。
- 前端 API、轮询与结构组件采用 TDD；视觉布局通过真实浏览器 smoke。
- 最终执行后端全量覆盖率、隔离测试库 migration 往返、前端 test/lint/typecheck/build 和真实公开 Python 仓库验收。

## 风险与回滚

- 子进程隔离降低 parser crash 对 API 的影响，但不会提供完整容器沙箱；通过不执行代码、固定 argv、文件/时间/条目上限控制。
- 运行时 Python 语法版本可能与目标仓库不同；API 持久化精确 Python 版本，兼容性错误作为文件级证据。
- 进程重启可能留下 `indexing`；不在 M3 自动猜测恢复点。
- 回滚到 `20260814_02` 时将 `indexing/indexed` 退回 `cloned` 并删除 M3 表；M2 Snapshot 和工作区不变。
