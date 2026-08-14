# Tasks: M3

> doc_version: 2
>
> spec_deltas: `[{stage: T6, reason: "新任务直接 cloning→indexing；历史 cloned 保持终态", classification: "澄清性", at: "2026-08-14"}]`

- [x] **T1 — 规格、配置、模型与 migration** `[test_strategy: smoke]`
  - Gate 1 自检，新增资源配置、ORM 模型和 `20260814_03` migration。
  - 在隔离测试库验证 upgrade、downgrade、upgrade。
- [x] **T2 — Python AST 提取器与隔离进程** `[test_strategy: tdd]`
  - RED：类/函数/Import/测试/编码/错误/限制测试。
  - GREEN：实现不可变 DTO、Visitor、runner 和固定 argv Parser Client。
- [x] **T3 — Code Index Service 与持久化** `[test_strategy: tdd]`
  - RED：一致性、状态、部分成功、原子写入、失败映射和读取预览测试。
  - GREEN：实现 Service 和结构化模型映射。
- [x] **T4 — Queue 流程与 Repository artifact 回归** `[test_strategy: regression]`
  - RED：克隆后自动索引、索引失败仍可读 Tree、SHA/clean 不一致测试。
  - GREEN：串联 processor，调整 Tree readiness 和任务终态。
- [x] **T5 — FastAPI Code Structure 契约** `[test_strategy: tdd]`
  - RED：200/404/409/422/503 和 no-store 测试。
  - GREEN：新增 Schema、依赖、路由和异常映射。
- [x] **T6 — Next.js M3 状态和结构展示** `[test_strategy: tdd]`
  - RED：API DTO、indexed 终态、失败后 Tree、结构组件测试。
  - GREEN：实现数据加载、结构预览和 M3 页面文案。
- [x] **T7 — 架构文档与 ADR** `[test_strategy: none]`
  - 更新 README、产品范围、架构、调用链、术语、项目配置和 ADR-007。
- [x] **T8 — 全量验证与真实浏览器验收** `[test_strategy: smoke]`
  - 后端覆盖率 ≥80%，前端 test/lint/typecheck/build 全绿。
  - 隔离测试库 migration 往返；真实公开 Python 仓库验证 `indexing → indexed`、刷新恢复、结构证据和停止轮询。
  - Gate 2、diff/文件尺寸/去冗余审计；保持未提交、未推送。

## Gate 2 证据

- 前端：8 个测试通过，ESLint、TypeScript 与 Next.js 生产构建通过；首页为静态路由，任务详情为动态路由。
- 后端：79 个测试通过，总覆盖率 87.18%，高于 80% 门槛；真实 PostgreSQL 回归测试覆盖规范化父子表写入顺序，并覆盖解析进程启动失败的错误映射。
- 数据库：独立 `issuepilot_test` 完成 `20260814_03 → 20260814_02 → 20260814_03 (head)` 往返。
- 浏览器：MarkupSafe 新任务真实经过 `cloning → indexing → indexed`；展示 12 个 Python 文件、116 个符号、53 个 Import、26 个测试，刷新后恢复一致，终态连续 5 秒无新轮询。
- 三方一致性：开发数据库 Snapshot/Index、页面和真实 Worktree HEAD 均为 `b2e4d9c7687be25695fffbe93a37622302b24fb1`，Worktree 为 clean。
- 缺陷闭环：首次浏览器索引暴露父子表落库顺序错误；新增真实数据库 RED 测试后分阶段 flush 修复，回归测试和第二轮浏览器流程均通过。
- 状态：M3 工程实现完成，等待产品负责人验收；未 Commit、未 Push、未进入 M4。
