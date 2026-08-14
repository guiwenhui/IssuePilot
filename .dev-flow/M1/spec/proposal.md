# Proposal: M1

## 背景与目标

M0 已建立产品、架构和安全边界。M1 要完成第一条真实请求链：用户从 Next.js 提交公开仓库 HTTPS URL 与 Issue，FastAPI 校验输入，通过 Task Service 将任务以 `created` 状态保存到 PostgreSQL，并允许页面按任务编号轮询查询。

成功意味着任务可以跨页面刷新持久化查询，不意味着仓库已经被克隆或 Agent 已开始执行。

## 范围

### 范围内

- Next.js 任务创建表单、任务详情页和固定间隔状态轮询。
- FastAPI 创建与查询任务接口、Pydantic 校验和统一错误格式。
- Task Service 创建和读取任务。
- PostgreSQL `tasks` 表与 Alembic migration。
- 前端、后端、数据库和浏览器验收。
- 更新 README、架构、调用链、ADR 和术语表。

### 范围外

- 仓库网络可达性、真实性、重定向、私网地址和仓库大小检查。
- 克隆、Worker、RQ、Redis、SSE。
- LangGraph、Checkpoint、Interrupt、审批、Patch 和测试命令执行。
- 状态自动推进、任务列表、取消、重试、Commit、Push 或真实 PR。

## 验收标准

- **AC1**：给定合法 HTTPS URL 和非空 Issue，当用户提交时，则 API 返回 `201`、UUID 和 `created`，PostgreSQL 存在内容一致的记录。
- **AC2**：给定已有任务，当用户直接打开或刷新任务详情页时，则页面通过查询 API 恢复并展示持久化记录。
- **AC3**：给定打开的任务详情页，当页面保持活动时，则前端产生不重叠的周期 GET，并展示最后同步时间。
- **AC4**：给定非法 URL、空 Issue、超长字段或额外字段，当提交时，则 API 返回结构化 `422` 且数据库不新增任务。
- **AC5**：给定不存在但格式合法的 UUID，当查询时，则 API 返回结构化 `404 TASK_NOT_FOUND`。
- **AC6**：给定数据库不可用，当创建或查询任务时，则 API 返回结构化 `503 DATABASE_UNAVAILABLE`，页面显示连接错误而不伪造任务业务状态。
- **AC7**：给定桌面或窄屏浏览器，当使用键盘和表单时，则标签、加载、禁用和错误状态可用且页面布局正常。

## 影响模块

- `app/`、`components/`、`lib/` —— 表单、任务页、轮询和 API 客户端。
- `backend/app/` —— FastAPI、契约、Service、ORM 和配置。
- `backend/migrations/` —— PostgreSQL Schema 版本管理。
- `backend/tests/` —— Service、API、数据库与错误路径测试。
- `docs/`、`README.md` —— 实际架构、调用链、决策和运行方式。

## 测试策略

- AC1 → PostgreSQL 集成测试 + API 测试 + 浏览器提交验证 `[test_strategy: tdd]`
- AC2 → API 查询测试 + 浏览器刷新验证 `[test_strategy: tdd]`
- AC3 → 前端定时轮询测试 + 浏览器网络证据 `[test_strategy: tdd]`
- AC4 → 参数化 API 校验测试与写入计数断言 `[test_strategy: tdd]`
- AC5 → API 404 契约测试 `[test_strategy: tdd]`
- AC6 → Service/路由异常映射测试 + 页面错误状态测试 `[test_strategy: tdd]`
- AC7 → lint、类型检查、production build、桌面与窄屏浏览器冒烟 `[test_strategy: smoke]`
