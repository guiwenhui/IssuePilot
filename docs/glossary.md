# IssuePilot 术语表

本文面向第一次接触 AI 全栈与 Agent 工作流的读者。表内同时注明 M1–M4 已实现能力和后续目标能力。

| 术语 | 初学者解释 | 在 IssuePilot 中的含义 |
|---|---|---|
| API | 两个程序之间约定好的通信入口，规定请求怎么传、响应怎么回。 | Next.js 通过 FastAPI API 创建和查询任务；M1 首次实现。 |
| API 契约 | API 对字段、类型、状态码和错误格式的明确约定。 | Pydantic 校验仓库 URL 与 Issue，OpenAPI 记录接口结构。 |
| DTO | Data Transfer Object，专门用于系统边界之间传输数据的结构。 | M1 的任务响应对外暴露 `task_id`、`issue` 等稳定字段，不让数据库列名直接决定 API。 |
| ORM | Object-Relational Mapping，用对象和类型描述数据库表及查询。 | M1 使用 SQLAlchemy ORM 映射 PostgreSQL 的 `tasks` 表。 |
| Migration | 可按顺序执行和回退的数据库结构变更脚本。 | M1 使用 Alembic 显式创建 `tasks` 表，应用启动不会自动改表。 |
| CORS | 浏览器对跨来源请求的安全规则，服务端需明确允许可信网页来源。 | M1 只允许配置的 Next.js Origin 调用 FastAPI，并限制到所需方法和请求头。 |
| 异步 Session | 一次异步数据库工作单元，管理查询、提交和回滚。 | Task Service 使用它创建和查询任务；数据库故障时回滚并映射为 `503`。 |
| 轮询（Polling） | 浏览器每隔一段时间主动询问服务器“状态变了吗”。实现简单，但会产生重复请求。 | M1 用轮询读取任务状态，先验证最小调用链。 |
| SSE | Server-Sent Events，服务器通过一条长连接持续向浏览器推送单向事件。 | 后续实时展示 Agent 进度的候选升级，不属于 M1。 |
| Worker | 专门在 HTTP 请求之外运行耗时任务的后台执行者。 | M2 起负责克隆和后续索引、工作流任务；M1 不启动耗时任务。 |
| 背压（Backpressure） | 当任务来得比处理更快时，通过容量和并发限制阻止资源无限增长。 | M2 的队列容量为 20、单消费者；队列满时任务保存明确失败。 |
| SSRF | 服务端被输入诱导去访问内网或不应访问的地址。 | M2 首版只允许 `github.com`，不把任意 HTTPS Host 交给 Git。 |
| 浅克隆 | 只获取最近历史的 Git 克隆方式，减少网络、时间和磁盘使用。 | M2 使用 `depth=1` 固定当前 HEAD，不获取完整历史。 |
| Staging 目录 | 结果对外生效前使用的临时隔离目录。 | M2 先在 UUID staging 克隆和验证，成功后才原子移动到正式任务目录。 |
| Commit SHA | 唯一标识一次 Git 提交的哈希。 | M2 保存并展示 40 位 HEAD SHA，证明文件树对应哪个版本。 |
| Manifest | 对一组文件及其元数据形成的受限清单。 | M2 保存 tracked path、类型和大小；它是证据，但不替代真实工作区。 |
| Submodule | Git 仓库中指向另一个仓库特定 Commit 的条目。 | M2 只把它标记为 `submodule`，不会递归初始化或访问其远程地址。 |
| 符号链接 | 文件系统中指向另一路径的特殊条目。 | M2 展示其类型，但计量与枚举不跟随链接到工作区外部。 |
| 状态机 | 把任务可能处于的状态和合法转换画清楚的规则。 | 防止前端或 Agent 随意跳过审批，将任务直接标为完成。 |
| LangGraph | 用节点、边和共享状态描述 Agent 工作流的框架。 | M5 用它显式编排检索、分析和规划，后续加入审批与恢复。 |
| Checkpoint | 在安全位置持久化一次工作流状态，类似游戏存档，但不保存模型完整思考过程。 | M6 用于服务中断后读取最后成功节点和状态继续执行。 |
| Interrupt | 工作流主动暂停并等待外部输入的机制。 | M6 在应用 Patch 前等待用户批准、修改或拒绝计划。 |
| 幂等性 | 同一个操作重复执行一次或多次，最终效果仍与执行一次相同。 | 恢复或重试前要避免重复创建任务、重复应用 Patch 等副作用。 |
| Worktree | Git 提供的额外工作目录，可让同一仓库的变更与原目录隔离。 | M7 在临时 Worktree 中应用 Patch 和测试，不改用户原仓库。 |
| Patch | 描述代码变更的文本。 | IssuePilot 只生成并应用本地 Patch，不 Push 或创建真实 PR。 |
| Unified Diff | 常见 Patch 格式，用 `+`、`-` 和上下文行表示文件改动。 | 页面用于展示待审查的精确代码差异。 |
| AST | 抽象语法树，把源代码解析成类、函数、导入等结构，而不是普通文本。 | M3 在隔离子进程中用标准库 AST 提取 Python 结构，不执行源码。 |
| 限定名 | 带完整父作用域的符号名称，可区分不同类或函数中的同名符号。 | M3 保存 `Service.run` 等限定名，为 M4 符号检索提供依据。 |
| Source Span | 一个语法结构在源码中的起止行范围。 | M3 保存符号的 `start_line/end_line`，让结果能引用真实位置。 |
| 代码索引快照 | 与某个 Commit 和解析器版本绑定的结构化代码产物。 | M3 的 `code_indexes` 记录 Commit、Python/Parser 版本和数量，子表保存文件、符号与 Import。 |
| 文件级解析警告 | 单个文件无法按当前 Python 语法或编码解析，但不抹掉其他成功结果。 | M3 保存 `syntax_error/read_error` 的受限摘要；至少一个文件成功时任务仍可 `indexed`。 |
| indexed | 结构化代码索引已完成的业务状态。 | M3 终态；只证明 AST 产物可核对，不表示已完成 M4 检索或 Issue 分析。 |
| Chunk | 带固定来源边界的可检索代码片段。 | M4 优先按 AST Symbol 起止行切分，超长 Symbol 使用重叠窗口；保存 path、行号和内容 hash。 |
| Embedding | 把文本或代码转换成一组数字，使语义相近内容在向量空间里更接近。 | M4 默认用本机 `qwen3-embedding:0.6b` 生成 1024 维向量，不调用 OpenAI。 |
| 混合检索 | 同时使用多种互补信号召回结果。 | M4 组合 PostgreSQL FTS、AST Symbol 和 pgvector 余弦相似度。 |
| 向量检索 | 根据 Embedding 距离查找语义相近内容。 | M4 对小仓库使用 exact cosine scan，与关键词和符号检索组合。 |
| RRF | Reciprocal Rank Fusion，只根据各通道名次融合，不直接比较不同量纲的原始分数。 | M4 使用 `1/(60+rank)` 汇总三路排名。 |
| Reranker | 对第一轮召回结果做更精细的重新排序。 | M4 使用确定性规则，根据多通道、Symbol、path 和测试意图加小幅 bonus；尚未使用 LLM。 |
| Recall@K | 正确结果中有多少出现在检索返回的前 K 项；越高表示遗漏越少。 | M4/M9 衡量相关文件召回能力，例如预期 4 个文件中前 10 项找到了 3 个，Recall@10 为 75%。 |
| pgvector | PostgreSQL 的向量扩展，让业务数据和向量索引可放在同一数据库中。 | M4 引入；M1 只使用 PostgreSQL 的普通业务表。 |
| retrieving | M4 正在生成 Chunk/Embedding 并执行混合检索的活跃状态。 | 浏览器继续轮询；失败会保存 Embedding、限制或一致性 failure code。 |
| retrieved | M4 检索证据已原子保存的业务终态。 | 浏览器停止轮询并读取 Retrieval API；不表示已经完成 M5 需求分析。 |
| Ollama | 在本机运行模型并提供 HTTP API 的运行时。 | M4 只通过 loopback `/api/embed` 生成公开仓库代码向量。 |
| RQ | 基于 Redis 的 Python 后台任务队列，负责排队和由 Worker 消费任务。 | M2 仍未引入；观察到真实重启丢失、多实例或排队需求后再评估。 |
| 质量 Gate | 只有满足测试、审查和边界条件才能进入下一阶段的门禁。 | M8 防止“模型说完成了”被当成真实完成。 |
| ADR | Architecture Decision Record，记录某项架构选择的背景、决定、替代方案和后果。 | M0 用 ADR 保存关键取舍，方便以后知道“为什么当时这样选”。 |

## 容易混淆的区别

- **轮询与 SSE**：轮询是浏览器反复问；SSE 是服务器持续推送。M1 先选轮询。
- **Checkpoint 与数据库备份**：Checkpoint 保存一次工作流执行状态；数据库备份保护整库数据，目的不同。
- **Memory 与 Checkpoint**：Memory 常指模型需要使用的历史信息；Checkpoint 主要服务于确定性的暂停和恢复。
- **RAG 与 Agent**：RAG 负责找上下文；Agent 工作流负责决定以什么顺序分析、审批、调用工具和验证结果。
- **Redis 与 RQ**：Redis 是数据/消息基础设施；RQ 才提供任务入队和 Worker 消费语义。
- **Snapshot 与工作区**：Snapshot 记录 Commit 和文件清单；工作区保存真实文件。恢复或读取结果时需要核对两者。
- **任务失败与 API 失败**：克隆失败是已创建任务的业务结果，GET Task 仍返回 200；请求格式、数据库或工作区契约错误使用对应 HTTP 状态码。
