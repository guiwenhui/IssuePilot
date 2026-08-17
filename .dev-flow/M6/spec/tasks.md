# Tasks: M6

> doc_version: 2
>
> spec_deltas: `[{stage: "legacy-bootstrap", reason: "LangGraph 顶层 namespace 运行时语义澄清", classification: "澄清性", at: "2026-08-17"}, {stage: "browser-acceptance", reason: "真实仓库检索重复 Chunk 与异常状态未收敛", classification: "范围性（用户已批准 mini-Gate）", at: "2026-08-17"}]`

> source: approved proposal.md + design.md
> development rule: no commit/push/merge until explicit post-acceptance approval

> product_acceptance: passed at 2026-08-17; commit/push authorized by product owner

> [SPEC-DELTA v1] 原因: LangGraph 1.2.11 将非空顶层 `checkpoint_ns` 解释为子图路径，导致 legacy `aupdate_state` 查找不存在的子图。顶层 namespace 改为空，仍用 task UUID thread_id 和业务 graph_version 隔离执行；属澄清性变更。

> [SPEC-DELTA v2] 原因: 真实仓库验收暴露父级/方法 Chunk 重合与后台异常未收敛。用户已批准在 M6 内补充去重、错误分类、队列兜底和卡死任务处理；不进入 M7。

## Round 3 — 真实仓库检索验收缺陷

- [x] **T17 — 重复 Chunk 与错误分类回归** `[test_strategy: regression]`
  - RED：父级最后窗口与方法范围重合时复现唯一键冲突；持久化约束错误不得伪装成数据库不可用。
  - GREEN：调用 Embedding 前确定性去重并保留更具体 Symbol；检索逻辑持久化错误保存稳定失败码。
- [x] **T18 — Repository Worker 状态收敛** `[test_strategy: regression]`
  - RED：未分类后台异常后 Task 不得永久停留在活跃状态。
  - GREEN：独立 Session 以单条活跃状态条件更新收敛失败；数据库错误保留 `DATABASE_UNAVAILABLE`，其它逃逸异常保存 `REPOSITORY_PIPELINE_FAILED`，且不覆盖并发终态。
- [x] **T19 — 卡死任务恢复与复验** `[test_strategy: regression]`
  - 核对 Snapshot SHA、Worktree HEAD/clean 与索引 Commit 后安全处理任务 `0cd95c14-812a-4496-9485-ac3a6dc3e123`。
  - 运行定向与后端全量测试，API 不再返回假活跃状态；保持未 Commit、未 Push、未进入 M7。

## Round 1 — 依赖、契约与持久化（最多 8 单元）

- [x] **T1 — PostgreSQL Checkpointer 运行时基线** `[test_strategy: smoke]`
  - 安装并锁定 `langgraph-checkpoint-postgres`，验证 Python 3.13 和当前 LangGraph 兼容。
  - 实现显式 setup 与 runtime schema verification；应用启动不得建表。
- [x] **T2 — M6 Schema 与状态机** `[test_strategy: tdd]`
  - 先写决定字段、comment 条件、Plan 状态/版本和 TaskStatus 测试。
  - 实现 request/response/history DTO 与稳定错误类型。
- [x] **T3 — 业务模型与 migration** `[test_strategy: smoke]`
  - 新增 PlanningDecision、Plan 版本关系、约束和索引。
  - 执行 upgrade/downgrade/upgrade roundtrip。
- [x] **T4 — Approval Store 幂等事务** `[test_strategy: tdd]`
  - 先写重复键、旧版本、非法状态、并发锁、apply/failed 和 v2 持久化测试。
  - 实现 pending intent、决定历史和恢复查询。
- [x] **T5 — LangGraph v2 Interrupt/Command** `[test_strategy: tdd]`
  - 先写暂停、三路条件、不可绕过、修改上限和 Checkpoint 配置测试。
  - 实现 approval/reject/revision 节点并保留 M5 证据校验。
- [x] **T6 — Revision Provider 链** `[test_strategy: tdd]`
  - 先写 Prompt Injection、原 Evidence、反馈长度和非法输出测试。
  - 实现本机 qwen3:8b plan-only revision 和 vN+1。
- [x] **T7 — Approval Service 三方核对与恢复** `[test_strategy: regression]`
  - 先写 Checkpoint/DB/HEAD/clean/hash 不一致、legacy bootstrap 和重启恢复测试。
  - 实现 submit/resume/reconcile，所有副作用幂等。
- [x] **T8 — Pending Decision Queue 与 runtime 装配** `[test_strategy: tdd]`
  - 先写单消费者、容量、启动重排、关闭和 disabled 回归。
  - 接入 lifespan、依赖工厂和 failure mapping。

## Round 2 — API、前端、验收与文档（最多 8 单元）

- [x] **T9 — Decision API 与错误契约** `[test_strategy: tdd]`
  - 新增 POST decisions，覆盖 202/404/409/422/503 和 no-store。
  - 扩展 Planning GET 的当前版本和决定历史。
- [x] **T10 — 前端 API、状态与轮询** `[test_strategy: tdd]`
  - 扩展 M6 状态、submitDecision、幂等键复用和 409 刷新策略。
  - active/terminal 状态轮询测试。
- [x] **T11 — 审批 UI** `[test_strategy: smoke]`
  - waiting_approval 显示批准/修改/拒绝；其它状态正确禁用或隐藏。
  - 展示 vN、历史、修订反馈、成功/失败和恢复阻塞。
- [x] **T12 — 真实 PostgreSQL 跨 Runtime 恢复** `[test_strategy: regression]`
  - 新建 Runtime 后从 Checkpoint 和 pending intent 恢复。
  - 覆盖 M5 waiting_approval bootstrap 与无计划 analyzing 安全重启。
- [x] **T13 — 真实 qwen3:8b Revision 冻结评测** `[test_strategy: smoke]`
  - MarkupSafe 反馈案例生成 v2，Schema/path/symbol/rank 校验通过。
- [x] **T14 — 全量自动化与浏览器验收** `[test_strategy: regression]`
  - 后端覆盖率 >=80%；前端 test/lint/typecheck/build；migration roundtrip。
  - 浏览器 approve、request_changes→v2、reject、刷新、停止轮询和 console。
- [x] **T15 — 文档、ADR 与安全边界** `[test_strategy: none]`
  - 更新 README、scope、architecture、call chains、glossary、ADR 和 project-config。
  - 记录本地模型、Checkpoint/业务表边界、M7 边界和回滚。
- [x] **T16 — Gate 2 去冗余与工作区审计** `[test_strategy: regression]`
  - DRY、函数<50、文件<800、无深嵌套、无 debug/敏感信息。
  - `git diff --check`；目标 Worktree HEAD/clean/digest 不变；`work/` 未触碰。
  - 保持未 Commit、未 Push、未进入 M7。

## Gate 2 证据

- 依赖：Python 3.13.15；LangGraph 1.2.11；`langgraph-checkpoint-postgres 3.1.2`；`pip check` 无破损依赖。
- Migration：隔离库完成 `20260817_06 → 20260817_05 → 20260817_06` 往返；新库从空库升级到 `20260817_06 (head)`，显式 Checkpoint setup 与启动 verify 成功。
- 后端：`200 collected / 197 passed / 3 live skipped`，branch coverage `83.98%`；包括并发同幂等键、M5 legacy bootstrap、跨 Factory Graph、跨 Session/Service pending intent 恢复，以及 Chunk 去重和原子失败收敛回归。
- 前端：11 项 Node test 全通过；ESLint、TypeScript、Next.js production build 全通过。
- 本地模型：`qwen3:8b` request_changes 冻结案例 22.18 秒通过，生成 v2 且 path/symbol/rank 仍受原 Evidence 约束。
- 浏览器：`03895d87-7dd0-413e-8677-8305bfcf85e4` approved；`690a19ad-8a8c-4050-8b4d-ea48e5423f5d` request_changes 后 v2 proposed；`b556f9da-1ddf-4910-8a0f-749c85312072` rejected。刷新保持终态/版本，干净标签页 console error/warn 为 0，终态后 5 秒无新 API 轮询。
- 缺陷复验：任务 `0cd95c14-812a-4496-9485-ac3a6dc3e123` 的 Snapshot、Code Index 与 Worktree HEAD 均为 `a605f8e31a27a69a71d7d7e244afe64ae73b7b99`，Worktree clean；原后台进程已退出，任务由守卫更新收敛为 `failed / RETRIEVAL_FAILED`，重启后 API 仍保持终态，页面停止轮询并保留 Tree/Code Structure。
- 修复验证：相关单元测试 25 项、PostgreSQL 定向集成测试 7 项通过；`python-symbol-v2` 在 Embedding 前去除父级/方法自然键重复，持久化约束错误不再冒充数据库不可用；两轮独立审查均无 CRITICAL/HIGH/MEDIUM。
- 安全恢复：首个任务的残留旧 Checkpoint 与新 Planning Run 不一致时真实进入 `recovery_blocked`，未误批准；清除隔离验收残留后 M5 无 Checkpoint bootstrap 才成功。
- Worktree：三任务 HEAD 均为 `b2e4d9c7687be25695fffbe93a37622302b24fb1`、clean=true、tree digest 均为 `df410ce10bcaed949e0090476273e0e70f3ff3b9`。
- 审计：`git diff --check` 通过；实现文件均少于 800 行；未发现 M7 Patch/Shell/pytest 执行入口；根目录 `work/` 仍为原未跟踪目录且无 M6 diff；未 Commit、未 Push。
