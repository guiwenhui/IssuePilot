# ADR-008：M4 本地混合代码检索

- Status: Accepted
- Date: 2026-08-16

## Context

M3 已提供与固定 Commit 绑定的 Python 文件和 Symbol，但 Issue 与代码命名可能使用不同词汇。纯关键词会漏掉语义相关代码，纯向量又可能弱化精确名称和来源证据。M4 需要可离线验收、可解释、不会提前引入 M5 Agent 的检索链。

## Decision

M4 采用三路召回：PostgreSQL `TSVECTOR` 关键词、M3 AST Symbol、pgvector 1024 维余弦相似度。每路最多 50 条，使用 RRF v1 `sum(1/(60+rank))` 融合，再用 rules v1 对多通道、Symbol/path 命中和测试意图做确定性小幅加分，最终保存前 10 条。

Embedding 通过 Provider 协议隔离，默认实现是本机 Ollama `qwen3-embedding:0.6b`。请求显式指定 1024 维和 `truncate=false`；文档批次最多 32，响应必须模型、数量、维度一致且全为有限数。M4 不调用 OpenAI API。

Chunk 优先采用 AST Symbol Source Span；超过 160 行时按 120 行窗口、20 行 overlap 切分，未被 Symbol 覆盖的模块级代码也进入受限 Chunk。`python-symbol-v2` 在 Embedding 前按 path、起止行和内容 hash 确定性去重父级窗口与子级 Symbol，冲突时保留更具体的方法/函数 Symbol；v1 不包含该去重规则。每条保存 path、Symbol、起止行、内容 hash、FTS 和向量。小型仓库使用 exact scan，不建立近似索引。

运行和结果持久化到 `retrieval_runs/retrieval_results`，保存固定 Commit、Issue hash、Provider/模型、Chunker/Fusion/Reranker 版本、候选数、每路 rank/score 与最终分数。读取前同时核对 Repository Snapshot、Code Index、Retrieval Run、Worktree HEAD 和 clean。

## Alternatives

### 纯 FTS + Symbol

部署最简单且完全确定，但 Issue 与代码用词不一致时召回不足，不能提供 M4 的语义价值。

### Voyage、Gemini 或 OpenAI 托管 Embedding

无需本机模型服务，可能有更强模型和弹性；但公开代码片段会离开本机，并增加费用、密钥、限流和网络失败边界。Provider 协议保留未来替换能力，本里程碑不启用。

### 独立向量数据库与 ANN

Qdrant、Milvus、Weaviate、HNSW 或 IVFFlat 更适合大规模数据，但当前小仓库 exact scan 已满足延迟和准确性，额外服务/索引调参缺少证据。

### LLM 或 Cross Encoder 重排

可能改善复杂语义排序，但增加新模型、延迟、成本和非确定性，并会模糊 M4 与 M5 边界。

## Consequences

- 代码不需要发送给 OpenAI；本地开发新增 Ollama 和约 639 MB 模型依赖。
- PostgreSQL 镜像必须提供 pgvector；普通 `postgres:16` 需安全迁移或使用独立测试容器。
- 三路排名和算法版本可解释、可刷新恢复并可回归测试。
- 重叠窗口不会重复生成 Embedding 或违反 `code_chunks` 唯一约束；约束等逻辑错误进入任务级检索失败，不冒充数据库连接故障。
- 冻结 MarkupSafe 五问题集的真实本地模型 Recall@10 为 100%，但样本小；M9 仍需扩大评测与对照实验。
- 进程内 Queue 的重启丢失限制没有改变；历史 `indexed` 不自动补排，持久恢复留给后续里程碑。
- M4 不生成需求分析、计划、Patch，不执行测试，也不 Commit、Push 或创建 PR。
