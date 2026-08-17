# Design: M4

> doc_version: 1
>
> spec_deltas: `[]`

## 架构决策

| 决策 | 理由 | 备选方案 |
|---|---|---|
| Ollama + `qwen3-embedding:0.6b` 为默认 Provider | 本地运行、无 API 密钥和代码外发，1024 维满足多语言与代码语义召回 | Voyage/Gemini/OpenAI 作为未来适配器；纯词法不满足语义价值 |
| pgvector `vector(1024)` | 与 PostgreSQL 任务事务、Commit 锚点和清理生命周期一致 | 独立向量库增加服务和一致性边界 |
| M4 使用 exact cosine scan | 目标仓库数据量小，exact 结果稳定且无需调参/建 ANN 索引 | HNSW/IVFFlat 在数据量和延迟证据出现后评估 |
| 三路召回后使用 RRF | FTS、Symbol、Vector 分数量纲不同，按名次融合更稳定 | 归一化加权分数对数据分布敏感 |
| 规则重排而非 LLM/Cross Encoder | 结果可复现、离线可测，不提前进入 M5 模型推理 | 学习型重排效果潜力更高但增加模型、延迟和不确定性 |
| 持久化运行和每条证据 | 刷新可恢复、能解释排名并进行离线评测 | 仅返回内存结果会丢失版本与审计证据 |
| 历史 `indexed` 不自动补排 | 内存队列不具备重启恢复语义，避免升级后伪装完成 | 后续持久队列/恢复能力再提供显式重跑 |

## 数据模型

### `code_chunks`

- `id UUID PK`
- `task_id FK code_indexes.task_id ON DELETE CASCADE`
- `file_id FK code_files.id ON DELETE CASCADE`
- `symbol_id FK code_symbols.id ON DELETE SET NULL`
- `commit_sha CHAR(40)`、`path VARCHAR(4096)`
- `kind VARCHAR(32)`、`symbol_name VARCHAR(2048) NULL`
- `start_line/end_line INTEGER`
- `content TEXT`、`content_sha256 CHAR(64)`
- `search_vector TSVECTOR`（由应用写入 `to_tsvector('simple', searchable_text)`）
- `embedding VECTOR(1024)`
- 唯一约束 `(task_id, path, start_line, end_line, content_sha256)`；索引 task/path、symbol、GIN search_vector。

### `retrieval_runs`

- `id UUID PK`、`task_id FK tasks.id ON DELETE CASCADE`
- `commit_sha CHAR(40)`、`query TEXT`、`query_sha256 CHAR(64)`
- `embedding_provider/model/dimensions`
- `chunker_version/fusion_version/reranker_version`
- 三路候选数、结果数、`created_at`
- M4 每个任务只保留当前运行，`task_id` 唯一；重跑时在事务中替换。

### `retrieval_results`

- `run_id FK retrieval_runs.id ON DELETE CASCADE`
- `chunk_id FK code_chunks.id ON DELETE CASCADE`
- `rank INTEGER`、`rrf_score DOUBLE PRECISION`、`rerank_score DOUBLE PRECISION`
- `keyword_rank/symbol_rank/vector_rank INTEGER NULL`
- `keyword_score/vector_score DOUBLE PRECISION NULL`
- `matched_channels JSONB`
- 主键 `(run_id, rank)`，并唯一 `(run_id, chunk_id)`。

检索产物、运行、结果和任务 `retrieved` 在一个事务提交。Embedding 网络调用和候选计算发生在事务写入前，避免长事务占用连接。

## Chunk 规则

- 输入只来自 `GitClient.tracked_entries()` 返回的普通 `.py`，并在读取前通过 `verify_workspace()`。
- 已成功解析的 Symbol 以完整起止行为首选 Chunk，搜索文本为 `path + qualified_name + signature + content`。
- 无 Symbol 覆盖的模块级连续代码按最多 120 行切分；超过 160 行的 Symbol 以 120 行窗口、20 行 overlap 稳定切分。
- 空白 Chunk 丢弃；内容最长 16 KiB；单任务最多 10,000 Chunk、Embedding 批次最多 32。
- Chunk 顺序固定为 `(path, start_line, end_line, symbol_name)`，ID 使用 UUID，但排序不依赖 UUID。

## Embedding Provider 边界

```python
class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Ollama 实现调用 `POST {base_url}/api/embed`，JSON 为 `{"model": ..., "input": [...], "dimensions": 1024, "truncate": false}`。文档与查询使用不同的固定前缀，查询前缀明确要求检索可回答 Issue 的 Python 代码。响应必须模型和数量一致、每个向量恰好 1024 维且全为有限数；超出上下文时失败而不是静默截断。

配置：`embedding_provider=ollama`、`ollama_base_url=http://127.0.0.1:11434`、`embedding_model=qwen3-embedding:0.6b`、`embedding_dimensions=1024`、`embedding_timeout_seconds=60`、`embedding_batch_size=32`。

## 召回、融合和重排

- **Keyword lane**：`websearch_to_tsquery('simple', query)`；按 `ts_rank_cd` 降序、稳定键排序，取 50。
- **Symbol lane**：从 Issue 提取字母数字/下划线 token，以 lower name/path 的 exact、prefix、substring 分级打分，取 50。
- **Vector lane**：query embedding 与 `code_chunks.embedding` 余弦距离 exact scan，取 50。
- **RRF v1**：`sum(1 / (60 + rank))`；缺席通道不加分。
- **Reranker v1**：在 RRF 基础上加入可解释小幅 bonus：多通道命中、symbol token exact、测试/源码意图词匹配、path basename 命中；最终以 `rerank_score DESC, rrf_score DESC, path, start_line, chunk_id` 排序。
- API 返回前 10 条；持久化每条 lane rank/score 和 matched channels，便于解释与回归。

## 状态与流程

```text
created → queued → cloning → indexing → retrieving → retrieved
                     ↘ failed     ↘ failed       ↘ failed

历史 M2 cloned、历史 M3 indexed：保持稳定终态，不自动补排
```

M3 `CodeIndexService` 接受 `success_status`，M4 新流水线让索引事务直接进入 `retrieving`，避免浏览器在 `indexed` 短暂窗口停止轮询。禁用检索或历史任务仍可稳定停在 `indexed`。

## API 契约

`GET /api/v1/tasks/{task_id}/retrieval`

```json
{
  "task_id": "uuid",
  "commit_sha": "40-char sha",
  "query": "issue text",
  "embedding": {"provider": "ollama", "model": "qwen3-embedding:0.6b", "dimensions": 1024},
  "versions": {"chunker": "python-symbol-v1", "fusion": "rrf-v1", "reranker": "rules-v1"},
  "created_at": "timestamp",
  "counts": {"chunks": 120, "keyword_candidates": 50, "symbol_candidates": 18, "vector_candidates": 50, "results": 10},
  "results": [{
    "rank": 1,
    "path": "src/example.py",
    "symbol": "Example.run",
    "start_line": 10,
    "end_line": 28,
    "snippet": "...",
    "matched_channels": ["keyword", "symbol", "vector"],
    "channel_ranks": {"keyword": 2, "symbol": 1, "vector": 4},
    "rrf_score": 0.0479,
    "rerank_score": 0.0779
  }]
}
```

错误：`404 TASK_NOT_FOUND`、`409 RETRIEVAL_NOT_READY`、`409 WORKSPACE_INCONSISTENT`、`422 VALIDATION_ERROR`、`503 DATABASE_UNAVAILABLE`。所有响应 `Cache-Control: no-store`。

## 失败契约

- `EMBEDDING_UNAVAILABLE`：Ollama 连接、超时或非成功 HTTP。
- `EMBEDDING_INVALID_RESPONSE`：数量、维度或数值非法。
- `RETRIEVAL_LIMIT_EXCEEDED`：Chunk 数量/内容资源上限。
- `RETRIEVAL_FAILED`：未分类的检索逻辑/数据库前计算失败。
- `WORKSPACE_INCONSISTENT`：Snapshot/Index/HEAD/clean/tracked 文件不一致。

失败任务保留已持久化的 M2 Tree 和 M3 Structure。错误消息不回显任意 Ollama 响应体、文件全文、堆栈或系统路径。

## 测试策略

- Chunk 边界、overlap、hash、tracked 安全和限制：TDD。
- Ollama 请求/响应/超时/维度验证：TDD，使用 MockTransport；一个本机 live smoke。
- RRF、规则重排、tie-break、三路证据：TDD。
- PostgreSQL/pgvector ORM、exact scan、事务和迁移往返：真实隔离数据库 integration。
- Pipeline、状态、失败保留 Tree/Structure：回归 + TDD。
- Retrieval API 200/404/409/422/503：TDD。
- Frontend 类型、终态、加载和证据展示：TDD + 浏览器 smoke。
- 冻结 MarkupSafe fixture：离线 Fake Embedding 评测 Recall@10 ≥ 80%；最终 live Ollama 另做证据。

## 回滚

1. 停止 API/前端/Ollama 调用。
2. Alembic downgrade 到 `20260814_03`；migration 先把 `retrieving/retrieved` 改为 `indexed`，再删结果、运行和 Chunk 表。
3. 若 `vector` extension 没有其他对象依赖则删除；否则保留扩展并记录。
4. 切回 M3 代码后，Tree 和 Code Structure 仍可从 Snapshot/Index 与真实工作区核对读取。

回滚不会删除仓库 Worktree、Repository Snapshot 或 M3 AST 表。
