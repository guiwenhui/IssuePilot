"use client";

import { useRef, useState } from "react";

import { ApiError, submitPlanningDecision } from "@/lib/api/tasks";
import type {
  Planning,
  PlanningDecisionAction,
  TaskStatus,
} from "@/lib/api/tasks";


type PlanningResultsProps = {
  planning: Planning;
  taskId: string;
  taskStatus: TaskStatus;
  onDecisionSubmitted: () => void;
};

function ranks(values: number[]): string {
  return values.map((value) => `#${value}`).join(" · ");
}

function decisionLabel(action: PlanningDecisionAction): string {
  return {
    approve: "批准",
    request_changes: "要求修改",
    reject: "拒绝",
  }[action];
}

function ApprovalControls({
  planning,
  taskId,
  onSubmitted,
}: {
  planning: Planning;
  taskId: string;
  onSubmitted: () => void;
}) {
  const [mode, setMode] = useState<PlanningDecisionAction | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pendingKey = useRef<string | null>(null);

  async function submit(action: PlanningDecisionAction) {
    setSubmitting(true);
    setError("");
    pendingKey.current ??= crypto.randomUUID();
    try {
      await submitPlanningDecision(taskId, {
        action,
        expected_plan_version: planning.plan.version,
        idempotency_key: pendingKey.current,
        comment: action === "approve" ? null : comment,
      });
      pendingKey.current = null;
      onSubmitted();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "审批请求失败，请重试。",
      );
      if (cause instanceof ApiError && cause.status === 409) {
        onSubmitted();
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="approval-controls" aria-labelledby="approval-title">
      <h3 id="approval-title">人工审批</h3>
      <p>批准只确认计划；M7 才能修改代码或运行目标仓库测试。</p>
      <div className="approval-actions">
        <button disabled={submitting} onClick={() => void submit("approve")}>
          批准计划
        </button>
        <button disabled={submitting} onClick={() => setMode("request_changes")}>
          要求修改
        </button>
        <button
          className="danger"
          disabled={submitting}
          onClick={() => setMode("reject")}
        >
          拒绝计划
        </button>
      </div>
      {mode && mode !== "approve" ? (
        <div className="approval-comment">
          <label htmlFor="decision-comment">
            {mode === "request_changes" ? "修改意见" : "拒绝原因"}
          </label>
          <textarea
            id="decision-comment"
            maxLength={2000}
            required
            value={comment}
            onChange={(event) => {
              pendingKey.current = null;
              setComment(event.target.value);
            }}
          />
          <div className="approval-actions">
            <button
              disabled={submitting || comment.trim().length === 0}
              onClick={() => void submit(mode)}
            >
              确认{decisionLabel(mode)}
            </button>
            <button disabled={submitting} onClick={() => setMode(null)}>
              取消
            </button>
          </div>
        </div>
      ) : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </section>
  );
}

export default function PlanningResults({
  planning,
  taskId,
  taskStatus,
  onDecisionSubmitted,
}: PlanningResultsProps) {
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
          <strong>
            {taskStatus === "waiting_approval"
              ? "等待人工审批"
              : "审批状态已保存"}
          </strong>
        <span>M6 会保存决定和 Checkpoint；批准后仍不会修改仓库代码。</span>
      </div>

      {taskStatus === "waiting_approval" && plan.status === "proposed" ? (
        <ApprovalControls
          planning={planning}
          taskId={taskId}
          onSubmitted={onDecisionSubmitted}
        />
      ) : null}

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

      {planning.decisions.length > 0 ? (
        <section className="decision-history">
          <h3>审批历史</h3>
          <ol className="planning-list">
            {planning.decisions.map((decision) => (
              <li key={decision.decision_id}>
                <strong>{decisionLabel(decision.action)} · v{decision.plan_version}</strong>
                <span>{decision.comment ?? "未填写补充说明"}</span>
                <small>
                  {decision.status}
                  {decision.failure_message
                    ? ` · ${decision.failure_message}`
                    : ""}
                </small>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
}
