"use client";

import RepositoryTree from "@/components/repository-tree";
import CodeStructure from "@/components/code-structure";
import RetrievalResults from "@/components/retrieval-results";
import PlanningResults from "@/components/planning-results";
import ImplementationResults from "@/components/implementation-results";
import type { Task } from "@/lib/api/tasks";
import { useTaskStatus } from "@/lib/use-task-status";


type TaskStatusPanelProps = {
  taskId: string;
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function TaskDetails({ task }: { task: Task }) {
  return (
    <dl className="task-details">
      <div>
        <dt>任务编号</dt>
        <dd className="mono">{task.task_id}</dd>
      </div>
      <div>
        <dt>公开仓库</dt>
        <dd>{task.repository_url}</dd>
      </div>
      <div>
        <dt>Issue</dt>
        <dd>{task.issue}</dd>
      </div>
      <div>
        <dt>创建时间</dt>
        <dd>{formatTimestamp(task.created_at)}</dd>
      </div>
    </dl>
  );
}

function TaskSummary({ task, lastSyncedAt }: { task: Task; lastSyncedAt?: Date }) {
  const isCloned = task.status === "cloned";
  const isIndexed = task.status === "indexed";
  const isIndexing = task.status === "indexing";
  const isRetrieving = task.status === "retrieving";
  const isRetrieved = task.status === "retrieved";
  const isAnalyzing = task.status === "analyzing";
  const isWaitingApproval = task.status === "waiting_approval";
  const isDecisionPending = task.status === "decision_pending";
  const isRevising = task.status === "revising";
  const isApproved = task.status === "approved";
  const isRejected = task.status === "rejected";
  const isRecoveryBlocked = task.status === "recovery_blocked";
  const isFailed = task.status === "failed";
  const isPatchReady = task.status === "patch_ready";
  const isTested = task.status === "tested";
  const isTestFailed = task.status === "test_failed";
  return (
    <>
      <div className="task-status-heading">
        <div>
          <p className="card-label">PERSISTED TASK</p>
          <h1>
            {isTested
              ? "本地 Patch 测试已通过"
              : isTestFailed
                ? "本地 Patch 测试未通过"
                : isPatchReady
                  ? "本地 Patch 等待测试授权"
                  : isApproved
              ? "实施计划已批准"
              : isRejected
                ? "实施计划已拒绝"
                : isRecoveryBlocked
                  ? "恢复校验未通过"
                  : isRevising
                    ? "正在按反馈修订计划"
                    : isDecisionPending
                      ? "审批决定正在处理"
                      : isFailed
                        ? "任务处理失败"
                        : isWaitingApproval
              ? "实施计划等待人工审批"
              : isRetrieved
              ? "相关代码证据已准备好"
              : isIndexed
              ? "代码结构已准备好"
              : isCloned
                ? "仓库已准备好"
                : "任务处理中"}
          </h1>
        </div>
        <span
          className={`status-pill ${
            task.status === "failed" || isRejected || isRecoveryBlocked || isTestFailed
              ? "danger"
              : "success"
          }`}
        >
          <span className="dot" />
          {task.status}
        </span>
      </div>
      <TaskDetails task={task} />
      <p className="polling-note">
        {isTested
          ? "白名单 pytest 已在无网络受限容器中真实通过；M8 尚未执行代码审查。"
          : isTestFailed
            ? "Patch 已保留，pytest 返回失败证据；M7 不会自动修改或重试。"
            : isPatchReady
              ? "Patch 已写入隔离 Worktree；请先审查 Diff，再明确授权运行 pytest。"
              : isApproved
          ? "人工已批准当前计划；可以单独授权在隔离 Worktree 生成本地 Patch。"
          : isRejected
            ? "人工已拒绝当前计划；任务停止，不会进入代码修改。"
            : isRecoveryBlocked
              ? "Checkpoint、PostgreSQL 或真实工作区不一致；已停止自动恢复，需要人工检查。"
              : isRevising
                ? "本地 qwen3:8b 正在使用原始代码证据和人工反馈生成新版计划。"
                : isDecisionPending
                  ? "审批请求已持久化，后台正在核对 Checkpoint、业务状态和真实工作区。"
                  : isFailed
                    ? "任务已停止；下方保留最后成功证据和可审查的失败原因。"
                    : isWaitingApproval
          ? "请审批当前计划；批准只确认计划，M6 不会修改代码。"
          : isRetrieved
          ? "三路检索结果已绑定固定 Commit，并保存每个通道的排名证据。"
          : isIndexed
          ? "Python AST 索引已绑定固定 Commit；没有导入或执行仓库代码。"
          : isCloned
            ? "仓库已在隔离目录完成浅克隆；这是 M2 历史终态。"
            : isIndexing
              ? "正在隔离进程中解析 Python 结构；不会启动 Agent。"
              : isRetrieving
                ? "正在本机执行关键词、Symbol 与向量召回；不会把代码发送给 OpenAI。"
              : isAnalyzing
                ? "正在本机使用 qwen3:8b 生成结构化分析；代码证据不会离开本机。"
              : "正在校验并克隆公开仓库；不会执行其中的代码。"}
        {lastSyncedAt
          ? ` 最近同步：${lastSyncedAt.toLocaleTimeString("zh-CN")}`
          : ""}
      </p>
      {task.failure ? (
        <div className="task-failure" role="alert">
          <strong>{task.failure.code}</strong>
          <span>{task.failure.message}</span>
        </div>
      ) : null}
    </>
  );
}

export default function TaskStatusPanel({ taskId }: TaskStatusPanelProps) {
  const {
    task,
    repositoryTree,
    codeStructure,
    retrieval,
    planning,
    implementation,
    error,
    lastSyncedAt,
    refresh,
  } = useTaskStatus(taskId);
  if (!task && !error) {
    return <p className="loading-state">正在读取 PostgreSQL 中的任务状态…</p>;
  }

  return (
    <div className="task-status-panel" aria-live="polite">
      {task ? <TaskSummary task={task} lastSyncedAt={lastSyncedAt} /> : null}
      {repositoryTree ? <RepositoryTree tree={repositoryTree} /> : null}
      {codeStructure ? <CodeStructure structure={codeStructure} /> : null}
      {retrieval ? <RetrievalResults retrieval={retrieval} /> : null}
      {planning && task ? (
        <PlanningResults
          planning={planning}
          taskId={taskId}
          taskStatus={task.status}
          onDecisionSubmitted={refresh}
        />
      ) : null}
      {planning && task && (implementation || [
          "approved",
          "implementation_pending",
          "generating_patch",
          "patch_ready",
          "test_pending",
          "testing",
          "tested",
          "test_failed",
        ].includes(task.status)) ? (
        <ImplementationResults
          taskId={taskId}
          taskStatus={task.status}
          planVersion={planning.plan.version}
          implementation={implementation}
          onSubmitted={refresh}
        />
      ) : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </div>
  );
}
