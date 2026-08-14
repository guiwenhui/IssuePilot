"use client";

import RepositoryTree from "@/components/repository-tree";
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
  return (
    <>
      <div className="task-status-heading">
        <div>
          <p className="card-label">PERSISTED TASK</p>
          <h1>{isCloned ? "仓库已准备好" : "任务处理中"}</h1>
        </div>
        <span className={`status-pill ${task.status === "failed" ? "danger" : "success"}`}>
          <span className="dot" />
          {task.status}
        </span>
      </div>
      <TaskDetails task={task} />
      <p className="polling-note">
        {isCloned
          ? "仓库已在隔离目录完成浅克隆；不会执行其中的代码。"
          : "正在校验并克隆公开仓库；不会启动 Agent 或执行代码。"}
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
  const { task, repositoryTree, error, lastSyncedAt } = useTaskStatus(taskId);
  if (!task && !error) {
    return <p className="loading-state">正在读取 PostgreSQL 中的任务状态…</p>;
  }

  return (
    <div className="task-status-panel" aria-live="polite">
      {task ? <TaskSummary task={task} lastSyncedAt={lastSyncedAt} /> : null}
      {repositoryTree ? <RepositoryTree tree={repositoryTree} /> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </div>
  );
}
