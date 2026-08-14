# ADR-001：前后端与服务边界

- Status: Accepted
- Date: 2026-08-13

## Context

IssuePilot 同时需要交互页面、业务 API、Python 代码分析和 Agent 工作流。若把相同业务规则分别放入 Next.js 与 FastAPI，会造成职责重复和状态不一致；若一开始拆为多个微服务，则会增加部署、通信和可观测性负担。

## Decision

采用单仓库、前后端模块分离的结构：

- Next.js 只负责页面渲染、表单、状态展示和审批交互。
- FastAPI 拥有 API 契约、输入校验、业务规则和状态转换。
- Task Service 封装任务业务逻辑，PostgreSQL 是任务状态的权威来源。
- 耗时工作通过 Worker 抽象在 HTTP 请求之外执行；M1 不启动耗时工作流。

FastAPI 返回 API 数据，不承担网页视觉渲染。该边界从 M1 首次落地。

M1 实现采用浏览器直接调用 FastAPI：表单与状态面板是 Next.js Client Components，FastAPI 对配置的前端 Origin 开启显式 CORS。API 路由、Task Service、ORM Model 分层，前端不访问数据库，也不复制后端校验或状态转换规则。

## Alternatives

### Next.js 全栈一体化

优点是开发和部署入口更少。缺点是 Python AI 生态接入不自然，并可能把 Agent 业务分散在 TypeScript 与 Python 两套运行时。

### 微服务架构

优点是服务可独立扩缩容。缺点是当前规模会提前引入服务发现、分布式调用、部署和追踪复杂度。

### 单体 FastAPI 加服务端模板

优点是运行时单一。缺点是难以体现目标岗位所需的 Next.js 全栈交互能力，复杂前端状态管理也不够自然。

## Consequences

- 业务规则只有 FastAPI 一处权威实现，便于测试和解释。
- 前后端需要维护明确 API 契约。
- 项目保留两个运行时及其依赖管理成本。
- 后续若拆服务，应以真实性能或团队边界为依据，而不是预先拆分。
