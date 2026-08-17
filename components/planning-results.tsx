import type { Planning } from "@/lib/api/tasks";


type PlanningResultsProps = {
  planning: Planning;
};

function ranks(values: number[]): string {
  return values.map((value) => `#${value}`).join(" · ");
}

export default function PlanningResults({ planning }: PlanningResultsProps) {
  const { analysis, plan, run } = planning;
  return (
    <section className="planning" aria-labelledby="planning-title">
      <div className="planning-heading">
        <div>
          <p className="card-label">LOCAL STRUCTURED PLANNING</p>
          <h2 id="planning-title">需求分析与实施计划</h2>
        </div>
        <span>v{plan.version} · {plan.status}</span>
      </div>

      <div className="planning-notice" role="note">
        <strong>等待人工审批</strong>
        <span>M5 只生成可审查计划；批准、修改或拒绝将在 M6 实现。</span>
      </div>

      <dl className="planning-meta">
        <div><dt>Commit</dt><dd className="mono">{planning.commit_sha}</dd></div>
        <div><dt>本地模型</dt><dd>{run.provider} · {run.model}</dd></div>
        <div><dt>证据</dt><dd>{run.evidence_count} 项{run.evidence_truncated ? " · 已裁剪" : " · 完整"}</dd></div>
        <div><dt>Graph</dt><dd>{run.graph_version}</dd></div>
      </dl>

      <article className="planning-summary">
        <p className="card-label">ANALYSIS</p>
        <h3>需求结论</h3>
        <p>{analysis.summary}</p>
      </article>

      <div className="planning-grid">
        <section>
          <h3>验收标准</h3>
          <ol className="planning-list">
            {analysis.acceptance_criteria.map((item, index) => (
              <li key={`${index}-${item.id}`}>
                <strong>{item.id}</strong>
                <span>{item.description}</span>
                <small>证据 {ranks(item.evidence_ranks)}</small>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <h3>影响范围</h3>
          <ul className="planning-list">
            {analysis.affected_areas.map((area, index) => (
              <li key={`${index}-${area.path}-${area.symbol ?? "module"}`}>
                <strong className="mono">{area.path}</strong>
                <span>{area.symbol ? `${area.symbol} · ` : ""}{area.reason}</span>
                <small>证据 {ranks(area.evidence_ranks)}</small>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {analysis.constraints.length + analysis.assumptions.length > 0 ? (
        <div className="planning-grid planning-support">
          <section>
            <h3>约束</h3>
            <ul className="planning-list">
              {analysis.constraints.map((item, index) => (
                <li key={`${index}-${item.description}`}>
                  <span>{item.description}</span>
                  <small>证据 {ranks(item.evidence_ranks)}</small>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3>假设</h3>
            <ul className="planning-list">
              {analysis.assumptions.map((item, index) => (
                <li key={`${index}-${item.description}`}>
                  <span>{item.description}</span>
                  <small>证据 {ranks(item.evidence_ranks)}</small>
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}

      <section className="plan-steps">
        <h3>实施步骤</h3>
        <ol>
          {plan.steps.map((step) => (
            <li key={step.order}>
              <span className="step-number">{String(step.order).padStart(2, "0")}</span>
              <div>
                <h4>{step.title}</h4>
                <p>{step.description}</p>
                <p className="mono step-paths">{step.paths.join(" · ")}</p>
                <small>证据 {ranks(step.evidence_ranks)}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <div className="planning-grid planning-support">
        <section>
          <h3>测试策略</h3>
          <ul className="planning-list">
            {plan.test_strategy.map((item, index) => (
              <li key={`${index}-${item.description}`}>
                <span>{item.description}</span>
                <strong className="mono">{item.target_paths.join(" · ")}</strong>
                <small>证据 {ranks(item.evidence_ranks)}</small>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3>风险与约束</h3>
          {analysis.risks.length + plan.risk_notes.length === 0 ? (
            <p className="planning-empty">模型未识别出额外风险；仍需人工复核。</p>
          ) : (
            <ul className="planning-list">
              {analysis.risks.map((risk, index) => (
                <li key={`${index}-${risk.description}`}>
                  <span>{risk.description}</span>
                  <small>缓解：{risk.mitigation} · 证据 {ranks(risk.evidence_ranks)}</small>
                </li>
              ))}
              {plan.risk_notes.map((note, index) => (
                <li key={`${index}-${note}`}><span>{note}</span></li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}
