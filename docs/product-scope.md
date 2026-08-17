# IssuePilot 产品范围

## 文档状态

- 状态：M0–M6 已验收
- 日期：2026-08-17
- 性质：产品范围基线，并同步标注各里程碑的真实落地状态

IssuePilot 面向小型 Python 公开仓库。用户提交仓库 HTTPS 地址和 Issue 描述，系统定位相关代码、生成实施计划；用户批准后，系统在隔离工作区生成本地 Patch、运行白名单测试并审查结果。

## 用户价值

IssuePilot 帮助学习者和开发者看清一次需求从输入到验证的完整过程，并让高风险动作保持可审查、可拒绝、可恢复。系统不会把大模型建议直接等同于正确实现，最终结果必须由测试证据与人工验收共同确认。

## MVP 输入

- 一个无需认证即可读取的小型 Python 公开 Git 仓库 HTTPS URL。
- 一段自然语言 Issue 描述。
- 一个测试命令配置；MVP 只支持 `pytest` 白名单命令族，默认命令为 `pytest`。

## MVP 输出

- 需求摘要与验收标准。
- 相关文件、符号和引用依据。
- 实施计划与风险提示。
- 等待人工批准的计划。
- 批准后生成的 Unified Diff 本地 Patch。
- 测试命令、输出摘要和退出码。
- 代码审查结果。
- 延迟、Token 使用量和工具调用次数等执行指标。
- 失败分类、最后成功节点和恢复入口。

## MVP 边界

第一版明确只支持：

- 小型 Python 公开仓库。
- 一个模型。
- 一种白名单测试命令族，默认 `pytest`。
- 在隔离仓库工作区生成本地 Patch。
- 用户批准计划后才允许修改隔离工作区。

第一版明确不支持：

- Java 或其他语言。
- 私有仓库认证。
- 自动 Commit、Push、合并或创建真实 PR。
- 任意 Shell 命令。
- 多模型路由或多 Agent 自由对话。
- 多用户权限系统。
- 自动执行数据库变更。
- 模型训练或微调。

## 成功标准

第一版成功不是“模型输出了代码”，而是用户能完成以下可验证闭环：

1. 提交仓库与 Issue，获得可查询的任务编号。
2. 查看系统引用的代码依据、需求分析和实施计划。
3. 明确批准、修改或拒绝计划。
4. 在不影响来源仓库的隔离工作区查看本地 Patch。
5. 查看真实执行的 `pytest` 命令、摘要和退出码。
6. 查看审查结论、失败证据和可恢复状态。

## 里程碑范围

| 里程碑 | 首次落地能力 | 不在该里程碑实现的能力 |
|---|---|---|
| M0 | 产品边界、目标架构、调用链、ADR、术语表 | 任何业务代码 |
| M1 | 页面提交任务、FastAPI 校验和保存任务、PostgreSQL 持久化、轮询状态 | 仓库克隆、Agent、SSE、Redis |
| M2 | URL 校验、公开仓库克隆、隔离目录和文件树 | 代码向量检索 |
| M3 | Python AST 解析，提取文件、类、函数、Import 和测试结构 | 向量融合与重排 |
| M4 | 关键词、符号、向量检索、融合、重排及 Recall@K | Patch 生成 |
| M5 | LangGraph 检索、分析、规划节点及显式状态 | 文件写入与测试 |
| M6 | Checkpoint、Interrupt、批准/修改/拒绝和恢复 | 真实 PR |
| M7 | 临时 Worktree、Unified Diff、Patch、`pytest` 白名单执行 | 任意命令、Push |
| M8 | Reviewer、质量 Gate、有限重试和人工升级 | 无限自动修复 |
| M9 | Trace、Token、延迟、Recall@K 和对照实验 | 模型训练 |
| M10 | Docker Compose、README、演示案例与开源交付 | 生产级多租户平台 |

## 当前实现状态

M1 已于 2026-08-14 通过产品验收：Next.js 表单可创建任务，FastAPI 使用 Pydantic 校验输入，Task Service 通过异步 SQLAlchemy 将任务写入 PostgreSQL，详情页每 3 秒非重叠轮询一次任务状态。

M2 已实现并通过验收：首版严格限制到公开 `github.com` 仓库；进程内单消费者队列在 HTTP 请求外执行 `ls-remote`、浅克隆、资源限制和文件树快照，任务状态可进入 `queued`、`cloning`、`cloned` 或 `failed`。页面在业务终态停止轮询，并展示固定 Commit、文件清单或持久化失败原因。

M2 不初始化 Submodule、不下载 LFS、不解析或执行仓库代码，也不支持私有认证或 GitHub 以外的 Host。Redis 与 RQ 仍未引入；进程重启会丢失内存队列，这是本里程碑的已知限制，待真实运行数据出现后再评估升级。

M3 已通过产品验收：新任务在 Repository Snapshot 落库后进入 `indexing`，隔离 Python 子进程使用标准库 AST 提取 tracked `.py` 文件、类、函数、方法、Import 和测试结构，结果以 `indexed` 终态绑定固定 Commit 保存到 PostgreSQL。单文件语法错误保留为警告；超时、超限、无 Python 文件或工作区不一致保存任务级失败证据。

M4 已通过产品验收：新任务在 AST 成功后直接进入 `retrieving`，按 Symbol 和模块边界生成带 path/行号/hash 的 Chunk；`python-symbol-v2` 在父级窗口与子级 Symbol 完全重合时于 Embedding 前确定性去重并保留更具体 Symbol。PostgreSQL FTS、M3 Symbol 和 pgvector 1024 维 exact cosine scan 各召回最多 50 条，经 RRF 和确定性规则重排后保存前 10 条证据并进入 `retrieved`。Embedding 默认由本机 Ollama `qwen3-embedding:0.6b` 生成，不调用 OpenAI API。检索逻辑失败和未分类 Worker 异常必须收敛任务状态，不能永久显示假 `retrieving`。

M4 不引入 LangGraph、LLM 需求分析、计划、Patch 或测试执行；升级前已经处于 `indexed` 的 M3 历史任务不会自动补排。读取结果时仍同时核对 Repository Snapshot、Code Index、Retrieval Run 和真实 Worktree HEAD/clean。冻结 MarkupSafe 评测集的真实本地模型 Recall@10 为 100%。

M5 已通过产品验收：新任务在 M4 原子保存检索证据后进入 `analyzing`，固定 LangGraph 四节点图依次加载证据、分析需求、生成计划并保存结果。`qwen3:8b` 只通过 loopback Ollama 读取最多 10 条、总计最多 20,000 字符的公开代码证据；Structured Output 还必须通过 Pydantic 和 path/symbol/rank 确定性校验。成功后任务进入 `waiting_approval`，页面明确提示 M6 才能批准、修改或拒绝。

M5 不使用 Checkpoint、Interrupt、工具循环或持久队列，不写仓库、不生成 Patch、不执行测试。服务在 `analyzing` 期间重启不能恢复当前模型调用；升级前的 `retrieved` 历史任务不会自动补排。关闭 `PLANNING_ENABLED` 后新任务继续以 M4 `retrieved` 为终态。

M6 已通过产品验收：PostgreSQL Checkpointer 在 `persist_plan` 后保存图状态并通过 Interrupt 暂停。用户决定先以幂等键和计划版本写入 `planning_decisions`，再由单消费者执行；approve/reject 成为业务终态，request_changes 使用同一 Commit、Analysis 和 Evidence 生成 vN+1。服务启动会重排 pending decision 和可恢复 analyzing task。

M6 恢复不会只信任 Checkpoint 或业务表。系统必须同时核对 Graph/Prompt、Planning Run、Evidence hash、Snapshot/Index/Retrieval Commit、Worktree HEAD 和 clean；不一致进入 `recovery_blocked`。M5 已保存但无 Checkpoint 的计划可在首次决定时安全 bootstrap。M6 仍不写文件、不生成 Patch、不运行目标仓库测试，也不 Commit、Push 或创建 PR。

## 人工审批边界

以下操作必须暂停并等待用户确认：

- 应用或修改 Patch。
- 执行白名单测试命令。
- 将来若扩展到 Commit、Push 或 PR，必须另行设计并再次审批；这些操作不属于当前 MVP。
- 修改数量或范围超出已批准计划的文件。
- 从失败状态恢复会产生新的副作用时。

## 数据与保密

演示和评测仅使用公开仓库、公开 Issue 或自行构造的数据。项目不得包含公司代码、内部 Jira 内容、内部 GitLab 数据或内部 Skill 源码。
