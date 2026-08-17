# Tasks: M4

> doc_version: 1
>
> spec_deltas: `[]`

- [x] **T1 — 规格、运行时探测、模型与 migration** `[test_strategy: smoke]`
  - 固定 proposal/design/tasks，检查 Ollama 和 PostgreSQL `vector` 可用性。
  - 先写 migration/schema 测试，再增加 pgvector、M4 ORM、配置和可回退 migration。
- [x] **T2 — Chunker 与资源边界** `[test_strategy: tdd]`
  - RED：Symbol/模块级/超长切分、overlap、行号、哈希、tracked 安全和上限。
  - GREEN：实现确定性 Python Chunk 生成，不执行仓库代码。
- [x] **T3 — Embedding Provider** `[test_strategy: tdd]`
  - RED：Ollama 批次/查询请求、超时、HTTP、数量、1024 维和有限数验证。
  - GREEN：实现 Provider 协议、Ollama HTTP 适配器和 Fake 测试替身。
- [x] **T4 — 三路召回、RRF 与重排** `[test_strategy: tdd]`
  - RED：FTS/Symbol/Vector 候选、RRF、业务 bonus、tie-break 和通道证据。
  - GREEN：实现 exact pgvector 查询和纯函数排名算法。
- [x] **T5 — Retrieval Service、流水线与持久化** `[test_strategy: tdd]`
  - RED：三方一致性、状态转换、原子结果、失败映射、历史 `indexed` 行为。
  - GREEN：M3 后自动检索，保存 Chunk/Run/Result，进入 `retrieved`。
- [x] **T6 — FastAPI 与 Next.js M4 证据页** `[test_strategy: tdd]`
  - RED：API 200/404/409/422/503、no-store、前端 DTO/终态/结果加载。
  - GREEN：Retrieval GET、M4 状态和证据展示。
- [x] **T7 — 文档、ADR 与离线 Recall@10** `[test_strategy: regression]`
  - 冻结 MarkupSafe 评测集并证明 Recall@10 ≥ 80%。
  - 更新 README、产品范围、架构、调用链、术语、项目配置和 ADR-008。
- [x] **T8 — 全量验证与真实浏览器验收** `[test_strategy: smoke]`
  - 后端覆盖率 ≥80%，前端 test/lint/typecheck/build 全绿，migration 往返。
  - 本机 Ollama 真实任务验证 `retrieving → retrieved`、刷新恢复、证据显示和停止轮询。
  - Gate 2、diff/文件尺寸/去冗余审计；保持未提交、未推送。

## Gate 2 证据

- 后端：114 个测试通过、1 个本地模型测试默认跳过；总覆盖率 86.34%，高于 80% 门槛。
- 本地模型：`qwen3-embedding:0.6b` 已下载；冻结 MarkupSafe 五问题集真实 Recall@10 = 1.000，各问题均为 1.0。
- PostgreSQL：独立 `pgvector/pgvector:pg16` 测试库完成 `20260816_04 → 20260814_03 → 20260816_04` 往返；M1/M3/M4 四个持久化集成回归通过。
- 前端：9 个测试通过，ESLint、TypeScript 和 Next.js 生产构建通过；首页为静态路由，任务详情为动态路由。
- 浏览器：真实 MarkupSafe 任务 `03466ac9-9db7-4159-97be-6133573707cc` 观察到 `retrieving → retrieved`；固定 Commit `b2e4d9c7687be25695fffbe93a37622302b24fb1`，132 个 Chunk，首位为 `escape_silent` 且命中三路。
- 刷新恢复：刷新后重新读取 PostgreSQL 和真实工作区，模型、Commit 和首位结果一致；终态后连续 6 秒无新增 API 请求。
- 缺陷闭环：真实数据库 RED 测试发现 `retrieval_results` 先于 `retrieval_runs` 写入的外键错误；显式 flush 修复并加入集成回归。
- 运行边界：现有 `postgres:16` 开发容器没有 vector 扩展，未被删除或替换；验收使用独立 54330 pgvector 容器，文档已标明安全升级要求。
- 状态：M4 已通过产品负责人验收；未 Commit、未 Push、未进入 M5。
