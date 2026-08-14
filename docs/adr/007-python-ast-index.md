# ADR-007：M3 Python AST 解析与结构化索引

- Status: Accepted
- Date: 2026-08-14

## Context

M2 已固定仓库 Commit 和真实工作区，M4 需要可按文件、符号和 Import 查询的结构化基础。不可信 Python 源码不能通过 Import 获得结构；直接在 FastAPI 解释器中解析复杂输入也会扩大 CPU、内存和崩溃影响。

## Decision

M3 使用 Python 标准库 `ast` 和 `tokenize.open`，在固定 argv、关闭 stdin、清理环境的独立 Python 子进程中只读解析 Git tracked 普通 `.py`。父进程复核 Repository Snapshot、目录、HEAD SHA 和 clean，限制 Python 文件数、单文件/总字节、结构条目和墙钟时间。

解析结果规范化保存到 `code_indexes`、`code_files`、`code_symbols` 和 `code_imports`，并绑定 Commit、Parser 版本和 Python 版本。新任务在 Snapshot 落库时进入 `indexing`，原子保存结构后进入 `indexed`。单文件语法/编码错误作为警告；整体无可用结果、超限、超时或工作区不一致进入 `failed`。

## Alternatives

### FastAPI 进程内直接解析

代码更少、无进程协议，但复杂或恶意 AST 输入会影响 API 主解释器和事件循环。

### 单个 JSONB AST 文档

早期写入简单，但 M4 的符号、路径和 Import 查询需要扫描大文档，分页和索引能力较差。

### Tree-sitter 或 LibCST

语法保真和多语言扩展更强，但 M3 只需要 Python 结构，新增依赖和版本管理尚无真实需求支撑。

## Consequences

- Parser 崩溃和超时与 FastAPI 主解释器隔离，且不执行仓库代码。
- 结构表可直接支持 M4 的关键词和符号召回，但本里程碑不实现检索或排名。
- 当前 Python 运行时语法与目标仓库可能不同，因此持久化精确版本并保留文件级解析警告。
- 进程重启仍可能留下 `indexing`，M3 不自动补排或伪恢复。
