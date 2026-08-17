# Proposal: M4 混合代码检索

> doc_version: 1
>
> status: accepted
>
> approved_at: 2026-08-16

## 用户价值

M3 已把固定 Commit 上的 Python 结构变成可核对的数据，但用户仍需要自己在大量文件和符号中找线索。M4 把 Issue 文本转成可解释的代码证据：同时使用关键词、AST Symbol 和向量语义召回，再以稳定规则融合和重排，让用户能看到“为什么这些代码最相关”，并为 M5 的需求分析和计划生成提供有 Commit 锚点的上下文。

## 范围

### 范围内

- 从 M3 已解析的 tracked Python 文件生成有边界、有行号、有内容哈希的代码 Chunk。
- 使用 PostgreSQL Full Text Search、M3 Symbol 查询和 pgvector 余弦距离形成三路召回。
- 默认通过本机 Ollama 调用 `qwen3-embedding:0.6b`，使用 1024 维向量；不调用 OpenAI API。
- 用 Reciprocal Rank Fusion（RRF）融合三路排名，再用确定性、可测试的业务规则重排。
- 保存每次检索运行、模型/算法版本、固定 Commit、各通道排名与最终结果。
- 新增 `retrieving → retrieved` 状态、新任务自动串联检索、只读 Retrieval API 和前端证据展示。
- 检索前及读取结果时复核 Snapshot SHA、Code Index SHA、Worktree HEAD 和 clean 状态。
- 建立冻结评测集，以 Recall@10 ≥ 80% 作为 M4 验收门槛。

### 范围外

- LangGraph、LLM Issue 分析、工具调用或计划生成（M5）。
- Patch、Worktree 修改、测试执行、Commit、Push 或 PR。
- 多语言代码解析或非 Python 文件的语义索引。
- 学习型/LLM 重排器、Cross Encoder、向量近似索引或 Redis。
- 为升级前已经停在 `indexed` 的历史任务自动补排检索。
- 对外部 Embedding 提供商做真实网络验收；M4 只保留可替换接口。

## 五个核心概念

1. **Chunk**：带 path、symbol、起止行和内容哈希的最小检索单元；它不是任意字符切片。
2. **Embedding**：把 Issue 和 Chunk 映射到同一 1024 维语义空间的数值向量。
3. **三路召回**：关键词匹配精确词，Symbol 匹配代码命名，向量匹配语义相近表达。
4. **RRF**：只依赖各通道名次的融合算法，避免直接比较量纲不同的 FTS 与向量分数。
5. **Recall@K**：前 K 个结果是否覆盖人工标注的相关 Chunk，用来验证检索没有漏掉关键证据。

## 完整调用链

```text
POST /api/v1/tasks
  → TaskService 持久化任务
  → 单消费者 RepositoryQueue
  → RepositoryService 固定公开仓库 Commit
  → CodeIndexService 在隔离子进程建立 AST 索引
  → RetrievalService 复核 Snapshot / Index / HEAD / clean
  → Chunker 从 tracked Python 源码与 Symbol 边界生成 Chunk
  → EmbeddingProvider → 本机 Ollama /api/embed
  → PostgreSQL 保存 code_chunks + vector(1024)
  → FTS / Symbol / Vector 三路召回
  → RRF 融合 → 确定性重排
  → 原子保存 retrieval_run/results，任务进入 retrieved
  → Next.js 轮询任务终态
  → GET /api/v1/tasks/{id}/retrieval
  → 再次复核三方状态并展示证据
```

## 方案比较

### 推荐方案

PostgreSQL FTS + M3 Symbol + pgvector exact scan + Ollama `qwen3-embedding:0.6b` + RRF + 确定性规则重排。

- 优点：本地、无 OpenAI 费用和密钥；三路互补；排名可解释；数据与业务状态同库；小仓库 exact scan 准确且运维简单。
- 代价：本机需要常驻 Ollama 和约 639 MB 模型；首次下载/加载慢；进程重启后的内存队列仍不恢复。

### 替代方案 A：纯 FTS + Symbol

- 优点：无模型和向量扩展，部署最简单。
- 缺点：Issue 与代码命名用词不一致时召回显著下降，无法达到 M4 的语义检索价值。

### 替代方案 B：托管 Embedding API

- 可使用 Voyage `voyage-code-4`、Gemini Embedding 或 OpenAI Embedding。
- 优点：无需本机模型服务，通常有更强模型和弹性。
- 缺点：代码片段离开本机、产生费用和密钥运维，并受网络/限流影响。

### 替代方案 C：独立向量数据库

- 可使用 Qdrant、Weaviate 或 Milvus。
- 优点：大规模 ANN、分片和专用向量能力更强。
- 缺点：M4 规模下引入额外服务、事务一致性和恢复边界，过早增加复杂度。

## 验收标准

- **AC1**：新任务完成 AST 后进入 `retrieving`，生成与 Snapshot/Index 相同 Commit 的 Chunk 和 Embedding，最后进入 `retrieved`。
- **AC2**：Chunk 只读取 tracked 普通 Python 文件，优先使用 AST Symbol 边界；超长 Symbol 稳定切分，且每个 Chunk 可回到 path 和起止行。
- **AC3**：Embedding Provider 使用固定模型、1024 维和批次上限；超时、连接失败、维度错误或非有限数值映射为稳定任务失败。
- **AC4**：同一 Issue 触发 FTS、Symbol、Vector 三路召回；RRF 与重排在相同输入下产生相同顺序，并保存通道证据。
- **AC5**：给定冻结 MarkupSafe 评测集，Recall@10 ≥ 80%，且测试不依赖外部网络。
- **AC6**：Snapshot、Index SHA、Worktree HEAD 或 clean 任一不一致时，不生成/返回旧检索结果，并给出 `WORKSPACE_INCONSISTENT`。
- **AC7**：检索未就绪、任务不存在、UUID 非法、数据库不可用分别返回稳定的 `409`、`404`、`422`、`503` 错误契约。
- **AC8**：刷新详情页后重新读取 PostgreSQL 和真实工作区，展示 Commit、查询、模型、结果 path/symbol/行号/snippet、通道和排名；`retrieved` 后停止轮询。
- **AC9**：Ollama 离线时任务进入 `failed`，保留 M2 Tree 和 M3 Structure 供核对，不伪装检索完成。
- **AC10**：migration 能 upgrade → downgrade → upgrade；回滚不删除 M2 Snapshot/M3 Index，并把 M4 状态安全退回 `indexed`。

## 影响模块

- `backend/app/retrieval` —— Chunk、RRF、确定性重排和评测纯逻辑。
- `backend/app/embeddings` —— Provider 协议与 Ollama HTTP 实现。
- `backend/app/models`、`backend/migrations` —— pgvector 扩展、Chunk、运行和结果表。
- `backend/app/services`、`backend/app/workers` —— 检索编排、状态、事务、一致性和失败映射。
- `backend/app/api`、`backend/app/schemas` —— Retrieval API、DTO 和错误契约。
- `lib`、`components`、`app` —— M4 状态、读取和证据展示。
- `docs`、`README.md`、`.codex/project-config.md` —— 更新真实边界、调用链、ADR 和术语。

## 风险与回滚

- Ollama 是新的本机运行时依赖；通过启动前配置、健康检查、超时和稳定失败码控制。
- Embedding 批次可能耗时或占内存；通过 Chunk/批次/总数上限控制，测试使用 Fake Provider。
- pgvector 可能不在现有 PostgreSQL 镜像中；在修改数据库运行环境前先只读检查，若需替换容器必须再次确认。
- FTS 对代码 token 和中文 Issue 的能力有限；以 Symbol 和向量召回互补，并用冻结评测集约束。
- 回滚到 M3 migration：把 `retrieving/retrieved` 任务退回 `indexed`，删除 M4 表和 vector extension（仅在无其他依赖时），保留 M3 产物与仓库工作区。
