# Tasks: M2

> doc_version: 2
>
> spec_deltas: `[{stage: "final-evidence", reason: "integration cleanup deleted a browser acceptance task from the development database", classification: "clarification", at: "2026-08-14"}]`

- [x] T1 固化 M2 proposal、design、状态流、API 和错误契约 `[test_strategy: none]`
- [x] T2 编写 URL 安全、M2 状态和数据模型测试，再实现 Schema/ORM `[test_strategy: tdd]`
- [x] T3 编写 Git 参数、超时、Manifest、路径和资源限制测试，再实现 GitClient/Workspace `[test_strategy: tdd]`
- [x] T4 编写克隆编排、Snapshot、队列和 Tree API 测试，再实现 Service/Worker/Router `[test_strategy: tdd]`
- [x] T5 编写前端终态与 Tree API 测试，再实现失败和文件树交互 `[test_strategy: tdd]`
- [x] T6 创建 M2 migration，验证 PostgreSQL upgrade/downgrade/upgrade 和状态流 `[test_strategy: smoke]`
- [x] T7 运行全量覆盖率、lint、类型、build 和批准仓库浏览器验收 `[test_strategy: smoke]`
- [x] T8 更新 README、产品范围、架构、调用链、ADR、术语表与 M2 状态 `[test_strategy: none]`

开发阶段不 Commit、不 Push。任何范围缺口先按文档优先协议写入 spec-delta。

## Gate 2 证据

- 前端：7 个测试通过，ESLint、TypeScript 与 Next.js 生产构建通过。
- 后端：58 个测试通过，分支覆盖率 90.46%，高于 80% 门槛。
- 数据库：独立 `issuepilot_test` 完成 `upgrade → downgrade → upgrade`，当前 revision 为 `20260814_02 (head)`；测试任务清理后为 0。
- 浏览器：批准的 MarkupSafe 仓库到达 `cloned`，固定 Commit `b2e4d9c7687be25695fffbe93a37622302b24fb1`，46 个条目、242,263 字节；刷新恢复、终态停止轮询、Tree 展示和非 GitHub 422 均通过。
- 双事实核对：开发数据库 Snapshot SHA 与真实工作区 HEAD 完全一致，工作区 clean。
- Spec Delta：集成测试已与开发业务数据库隔离，避免验收任务被测试清理。
- 状态：M2 工程实现完成，等待产品负责人验收；未 Commit、未 Push、未进入 M3。
