# Tasks: M1

> doc_version: 2
>
> spec_deltas: `[{stage: "browser-acceptance", reason: "404 caused repeated polling", classification: "clarification", at: "2026-08-13"}]`

- [x] T1 建立 FastAPI、SQLAlchemy、Alembic 项目骨架和配置 `[test_strategy: smoke]`
- [x] T2 编写 Task Schema URL/Issue 校验及错误契约测试，再实现校验 `[test_strategy: tdd]`
- [x] T3 编写 Task Service 创建、查询和数据库故障测试，再实现服务 `[test_strategy: tdd]`
- [x] T4 编写 POST/GET API 契约测试，再实现路由和异常映射 `[test_strategy: tdd]`
- [x] T5 创建 PostgreSQL `tasks` migration，并验证 upgrade/downgrade/upgrade `[test_strategy: smoke]`
- [x] T6 编写前端 API、创建表单和非重叠轮询测试，再实现页面交互 `[test_strategy: tdd]`
- [x] T7 运行 lint、类型检查、build、后端覆盖率和全链路浏览器验收 `[test_strategy: smoke]`
- [x] T8 更新 README、架构、调用链、ADR、术语表和 M1 状态 `[test_strategy: none]`

## Gate 2 证据

- 前端：5 个测试通过，ESLint、TypeScript 与 Next.js 生产构建通过。
- 后端：20 个测试通过，分支覆盖率 96.83%，高于 80% 门槛。
- 数据库：migration 已验证 `upgrade → downgrade → upgrade`，当前版本为 `20260813_01 (head)`。
- 浏览器：创建、持久化刷新、3 秒轮询、422、404 停止轮询、503 与移动端无横向溢出均完成真实验收。
- 状态：M1 已于 2026-08-14 通过产品负责人验收；尚未进入 M2。

开发阶段不 Commit、不 Push。发现范围缺口时先按文档优先协议更新本目录，再继续实现。
