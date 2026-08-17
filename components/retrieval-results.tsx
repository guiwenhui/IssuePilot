import type { Retrieval } from "@/lib/api/tasks";


type RetrievalResultsProps = {
  retrieval: Retrieval;
};

function score(value: number): string {
  return value.toFixed(4);
}

export default function RetrievalResults({ retrieval }: RetrievalResultsProps) {
  const { counts } = retrieval;
  return (
    <section className="retrieval" aria-labelledby="retrieval-title">
      <div className="retrieval-heading">
        <div>
          <p className="card-label">HYBRID RETRIEVAL</p>
          <h2 id="retrieval-title">与 Issue 相关的代码证据</h2>
        </div>
        <span>{counts.results} 结果 · {counts.chunks} Chunks</span>
      </div>

      <dl className="retrieval-meta">
        <div><dt>Commit</dt><dd className="mono">{retrieval.commit_sha}</dd></div>
        <div><dt>本地模型</dt><dd>{retrieval.embedding.model} · {retrieval.embedding.dimensions} 维</dd></div>
        <div><dt>查询</dt><dd>{retrieval.query}</dd></div>
        <div>
          <dt>候选</dt>
          <dd>关键词 {counts.keyword_candidates} · Symbol {counts.symbol_candidates} · 向量 {counts.vector_candidates}</dd>
        </div>
      </dl>

      <div className="retrieval-list">
        {retrieval.results.map((item) => (
          <article className="retrieval-card" key={`${item.rank}-${item.path}-${item.start_line}`}>
            <header>
              <span className="retrieval-rank">#{item.rank}</span>
              <div>
                <h3 className="mono">{item.path}</h3>
                <p>
                  {item.symbol ?? item.kind} · 行 {item.start_line}–{item.end_line}
                </p>
              </div>
              <div className="retrieval-channels" aria-label="命中通道">
                {item.matched_channels.map((channel) => (
                  <span className="code-tag" key={channel}>{channel}</span>
                ))}
              </div>
            </header>
            <pre><code>{item.snippet}</code></pre>
            <p className="retrieval-score">
              RRF {score(item.rrf_score)} · 重排 {score(item.rerank_score)}
              {Object.entries(item.channel_ranks).map(([channel, rank]) => (
                <span key={channel}> · {channel} #{rank}</span>
              ))}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
