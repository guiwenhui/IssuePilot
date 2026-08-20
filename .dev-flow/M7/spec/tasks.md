# Tasks: M7

> source: approved proposal.md + design.md
>
> doc_version: 1
>
> spec_deltas: `[]`
>
> development rule: no commit/push/merge until explicit post-acceptance approval

## Round 1 — 契约、数据与安全原语（最多 8 单元）

- [x] **T1 — M7 Schema 与状态契约** `[test_strategy: tdd]`
  - RED：Implementation/Test 请求、FileReplacement、响应和新 TaskStatus 的严格校验。
  - GREEN：实现版本/hash/幂等键、Patch/Test DTO 和错误类型。
- [x] **T2 — M7 业务模型与 migration** `[test_strategy: smoke]`
  - 新增 implementation_runs、patch_artifacts、test_runs、唯一约束与索引。
  - 新库 upgrade 和 head→down→head 往返。
- [x] **T3 — Implementation Store 幂等事务** `[test_strategy: tdd]`
  - RED：approved/version 守卫、并发同键、Patch/Test 原子保存和 pending 恢复。
  - GREEN：单条条件状态更新、稳定冲突和数据库错误映射。
- [x] **T4 — Worktree Manager** `[test_strategy: tdd]`
  - RED：固定 Commit、重复创建、路径 containment、来源 HEAD/clean/digest 不变。
  - GREEN：固定 Git argv 创建/核对隔离 Worktree，不清理有歧义目录。
- [x] **T5 — File Replacement 与 Patch Validator** `[test_strategy: tdd]`
  - RED：越权路径、traversal、symlink、hash、类型、字节/文件/行/Diff 限制。
  - GREEN：受限原子替换，Git 生成规范 Diff 并再次审计路径。
- [x] **T6 — 固定容器 Test Runner** `[test_strategy: tdd]`
  - RED：固定 argv、镜像、network/user/cap/resource 限制、timeout、输出截断与 hash。
  - GREEN：Runner adapter + Docker 实现；不可用时不降级宿主机。
- [x] **T7 — Implementation Graph 与 Checkpoint** `[test_strategy: tdd]`
  - RED：Patch review Interrupt、test Command、非法绕过和跨 Runtime 恢复。
  - GREEN：独立 graph/thread、节点幂等和三方不一致阻断。
- [x] **T8 — Implementation Queue 与启动恢复** `[test_strategy: tdd]`
  - RED：单消费者、背压、pending patch/test 重排、handler 失败和关闭。
  - GREEN：生命周期装配，不重复已完成副作用。

## Round 2 — API、UI 与验收（最多 8 单元）

- [x] **T9 — Implementation Service 编排** `[test_strategy: tdd]`
  - approved Plan/Commit/Evidence/来源 Worktree 核对，模型 Prompt、输出验证、Patch/Test 处理。
  - 错误保存稳定 failure code，已有 Patch 失败时仍保留。
- [x] **T10 — M7 API 与错误契约** `[test_strategy: tdd]`
  - POST implementation、GET、POST tests 覆盖 202/404/409/422/503/no-store。
  - 相同幂等键返回相同资源，expected version/hash 冲突停止。
- [x] **T11 — 前端 API、状态与轮询** `[test_strategy: tdd]`
  - M7 DTO、两次授权幂等键、active/paused/terminal 轮询规则。
  - 409 刷新权威状态，4xx 停止，网络/5xx 有限轮询。
- [x] **T12 — Patch 与测试证据 UI** `[test_strategy: smoke]`
  - approved 生成 Patch；patch_ready 展示 Diff/统计并授权 pytest。
  - tested/test_failed/failed/recovery_blocked 展示真实证据，不暴露绝对路径。
- [x] **T13 — PostgreSQL/Checkpoint/Git 跨进程恢复** `[test_strategy: regression]`
  - Patch Interrupt、test pending 和 Worktree 已写状态跨 Runtime 恢复。
  - 任一 hash/HEAD/clean/业务版本不一致进入 recovery_blocked。
- [x] **T14 — 真实 Runner、模型与浏览器验收** `[test_strategy: smoke]`
  - 固定 fixture 的 pass/fail/timeout、无网络非 root容器证据。
  - 本机 qwen3:8b 生成 Patch；浏览器两次授权、刷新、停止轮询和 console。
- [x] **T15 — 文档、ADR 与回滚** `[test_strategy: none]`
  - 更新 README、scope、architecture、call chains、glossary、project-config。
  - 新增 ADR-011，记录结构化替换、容器边界、替代方案和 M8 边界。
- [x] **T16 — Gate 2 全量验证与审查** `[test_strategy: regression]`
  - 后端 branch coverage >=80%；前端 test/lint/typecheck/build；migration roundtrip。
  - DRY、函数<50、文件<800、`git diff --check`；来源仓库不变；无 M8/Commit/Push/PR。

## Final evidence — 2026-08-17

- Backend：230 passed、7 skipped，coverage 80.74%。
- Frontend：12/12 tests passed；typecheck、lint、production build 全部通过。
- Fixed Docker Runner：3/3 live tests passed，覆盖 pass/fail、容器内硬超时、宿主超时清理、离线与非 root 边界。
- Local model：qwen3:8b live Patch generation 1/1 passed；M7 独立 300 秒预算生效。
- Migration：`07 -> 06 -> head -> 07` 隔离数据库往返通过。
- Recovery：真实 PostgreSQL Checkpoint 跨 Factory/Runtime 与 Git Worktree 恢复 13/13 passed。
- Browser：Patch 经第二次显式授权后在固定 Runner 中执行；缺少仓库依赖时诚实落为 `test_failed`，页面展示退出码、镜像摘要、完整输出 SHA256 和 `ModuleNotFoundError`。
- Review：最终严重级审查无 CRITICAL/HIGH/MEDIUM；`git diff --check` 通过，来源仓库 HEAD/clean 未改变，未实现 M8，未 Commit/Push/PR。
- Product acceptance：2026-08-20 通过 M7 产品验收。
