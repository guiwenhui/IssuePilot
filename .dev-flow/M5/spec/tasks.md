# Tasks: M5

> source: approved proposal.md + design.md
> development rule: no commit/push/merge until explicit approval

> [SPEC-DELTA v1] 原因: Python 3.13 基线回归暴露 M3 集成测试按全库统计 `code_files`，会被同一隔离测试库中的真实浏览器任务污染；这是测试隔离澄清，不改变产品范围或验收标准。先将断言限定到当前 `task_id`，再继续 M5。

> [SPEC-DELTA v2] 原因: Ollama 0.32.13 真实 `qwen3:4b` 预检证明 Pydantic Schema 中的 `minLength/maxLength` 会使本机 grammar 初始化返回 400；仅从发送给 Ollama 的兼容 Schema 移除这两个关键字，完整 Pydantic 长度校验仍在响应后执行，并新增回归测试。这是不降低业务边界的运行时兼容修正。

## Round 1 — 规格、运行时与后端核心（最多 8 单元）

- [x] **T1 — Python/LangGraph 运行时基线** `[test_strategy: smoke]`
  - 安装 Python 3.13，重新建立项目虚拟环境。
  - 将 `requires-python` 提升到 >=3.11，安装 `langgraph>=1.2,<2`。
  - 在新环境执行现有 M1–M4 全量后端测试，记录基线。
- [x] **T2 — Planning Schema 与确定性 Evidence Validator** `[test_strategy: tdd]`
  - 先写 Schema、长度/数量、rank/path/symbol、Patch/代码块拒绝测试。
  - 实现 Pydantic Draft/API DTO 与纯函数 Validator。
- [x] **T3 — Ollama Chat Provider** `[test_strategy: tdd]`
  - 先写 loopback、请求字段、结构化输出、timeout、体积、非法响应测试。
  - 实现 Provider 协议和 `qwen3:8b` Chat 客户端。
- [x] **T4 — LangGraph State、Context 与四节点图** `[test_strategy: tdd]`
  - 先写固定图拓扑、节点顺序、状态更新与无 Checkpointer 测试。
  - 实现 Prompt v1、Evidence Builder 和 Graph。
- [x] **T5 — Planning ORM 与 migration** `[test_strategy: smoke]`
  - 新增三张表、FK、唯一约束和 downgrade。
  - 执行 upgrade/downgrade/upgrade roundtrip。
- [x] **T6 — Planning Store 与事务** `[test_strategy: tdd]`
  - 先写真实 PostgreSQL Context、原子保存、重复执行、回滚、DTO 测试。
  - 实现 Store Protocol 与 SQL Store。
- [x] **T7 — Planning Service 与失败分类** `[test_strategy: tdd]`
  - 先写状态守卫、一致性、Provider/Schema/Evidence/数据库错误映射测试。
  - 实现 plan/get 与稳定 failure code。
- [x] **T8 — Pipeline、运行时装配和 Planning API** `[test_strategy: tdd]`
  - 先写 enabled/disabled、M4→analyzing→waiting_approval、历史兼容测试。
  - 新增依赖、路由、错误处理和 `GET .../planning` 契约。

## Round 2 — 前端、评测、文档与 Gate（最多 8 单元）

- [x] **T9 — 前端状态和 Planning API** `[test_strategy: tdd]`
  - 扩展 analyzing/waiting_approval、fetchPlanning 和错误降级测试。
- [x] **T10 — 分析与实施计划 UI** `[test_strategy: smoke]`
  - 展示模型/版本、摘要、验收标准、受影响区域、步骤、测试和风险。
  - 明确 M6 才能批准，不添加交互按钮。
- [x] **T11 — 真实 qwen3:8b 冻结评测** `[test_strategy: smoke]`
  - 拉取约 5.2 GB 模型。
  - MarkupSafe 案例验证 Schema、真实路径、生产代码步骤与回归测试步骤。
- [x] **T12 — 全量自动化与 migration 验证** `[test_strategy: regression]`
  - 后端全量测试与覆盖率 >=80%。
  - 前端测试、lint、typecheck、build。
  - migration roundtrip 与 M1–M5 PostgreSQL 集成测试。
- [x] **T13 — 真实浏览器验收** `[test_strategy: smoke]`
  - 观察 `analyzing → waiting_approval`。
  - 验证四类证据、刷新恢复、终态停止轮询和无控制台错误。
- [x] **T14 — 文档优先同步** `[test_strategy: none]`
  - 更新 README、product scope、architecture、call chains、glossary、ADR 和 project-config。
  - 记录 Python/模型/重启限制和 M6 边界。
- [x] **T15 — 去冗余与 Gate 2** `[test_strategy: regression]`
  - DRY、函数<50 行、文件<800 行、无深嵌套、无 debug/敏感数据。
  - `git diff --check`、工作区审计；确认 `work/` 未触碰且保持未跟踪。
  - 保持未 Commit、未 Push、未进入 M6。

## Gate 2 证据

- Python 运行时：`Python 3.13.15`；`python -m pip check` 返回 `No broken requirements found`。
- LangGraph：安装版本 `1.2.11`；固定拓扑仅包含 `retrieve_code → analyze_requirement → create_plan → persist_plan`，没有 Tool、循环或 Checkpointer。
- 本地模型：`ollama list` 显示 `qwen3:8b`（5.2 GB）和 `qwen3-embedding:0.6b`（639 MB）。
- Provider 回归：`tests/test_llm_provider.py` 共 16 项通过；真实 `qwen3:4b` 兼容预检 `1 passed in 33.48s`。
- 真实冻结评测：`RUN_OLLAMA_LIVE=1 ... test_planning_evaluation.py -m ollama -s` 使用 `qwen3:8b`，最终 `1 passed in 56.49s`。首次结果因非法 symbol 引用被 Evidence Validator 拒绝，收紧 Prompt 后通过，证明非法模型输出不会落库。
- 后端最终全量：独立临时 PostgreSQL 数据库上 `160 passed, 2 skipped in 1.63s`，总覆盖率 `86.92%`（门槛 80%）；临时数据库在回归后删除。
- 前端最终全量：Node Test `10 passed`；ESLint、TypeScript `--noEmit`、Next.js production build 全部通过；构建路由为 `/`、`/_not-found`、`/tasks/[taskId]`。
- Migration：独立临时数据库完成 `upgrade -> 20260817_05`、`downgrade 20260817_05 -> 20260816_04`、再 `upgrade -> 20260817_05`；roundtrip 通过。
- 真实浏览器任务：`a76e166b-cc42-474f-a4d1-a8fbcc5defd6`，Markupsafe 固定 Commit `b2e4d9c7687be25695fffbe93a37622302b24fb1`；实际观察到 `analyzing → waiting_approval`，四类证据和结构化计划可见。
- 浏览器刷新后从数据库恢复同一任务与计划；终态同步时间等待 6 秒保持不变，证明停止轮询；warning/error 日志为空；页面没有 M6 批准/拒绝按钮。
- 静态审计：`git diff --check` 通过；新增 Python 文件均小于 800 行，M5 新增函数均不超过 50 行；未发现 debug 或敏感凭据。
- 工作区：分支保持 `feat/M5`；未 Commit、未 Push；`work/` 保持未跟踪且未触碰；没有进入 M6。
