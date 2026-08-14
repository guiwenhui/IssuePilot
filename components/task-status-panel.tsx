"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, fetchTask, Task } from "@/lib/api/tasks";
import { PollHandle, schedulePoll, shouldRetryPoll } from "@/lib/polling";


type TaskStatusPanelProps = {
  taskId: string;
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export default function TaskStatusPanel({ taskId }: TaskStatusPanelProps) {
  const [task, setTask] = useState<Task>();
  const [error, setError] = useState("");
  const [lastSyncedAt, setLastSyncedAt] = useState<Date>();
  const timer = useRef<PollHandle | undefined>(undefined);

  useEffect(() => {
    let active = true;
    let controller: AbortController | undefined;

    async function loadTask() {
      let shouldRetry = true;
      controller = new AbortController();
      try {
        const currentTask = await fetchTask(taskId, controller.signal);
        if (active) {
          setTask(currentTask);
          setError("");
          setLastSyncedAt(new Date());
        }
      } catch (requestError) {
        if (active && !(requestError instanceof DOMException)) {
          if (requestError instanceof ApiError) {
            shouldRetry = shouldRetryPoll(requestError.status);
          }
          const message =
            requestError instanceof ApiError
              ? requestError.message
              : "连接失败，IssuePilot 将继续重试。";
          setError(message);
        }
      } finally {
        if (active && shouldRetry) {
          timer.current = schedulePoll(() => void loadTask());
        }
      }
    }

    void loadTask();
    return () => {
      active = false;
      controller?.abort();
      if (timer.current !== undefined) {
        clearTimeout(timer.current);
      }
    };
  }, [taskId]);

  if (!task && !error) {
    return <p className="loading-state">正在读取 PostgreSQL 中的任务状态…</p>;
  }

  return (
    <div className="task-status-panel" aria-live="polite">
      {task ? (
        <>
          <div className="task-status-heading">
            <div>
              <p className="card-label">PERSISTED TASK</p>
              <h1>任务已创建</h1>
            </div>
            <span className="status-pill success">
              <span className="dot" />
              {task.status}
            </span>
          </div>

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

          <p className="polling-note">
            当前仅保存任务，不会克隆仓库或启动 Agent。
            {lastSyncedAt
              ? ` 最近同步：${lastSyncedAt.toLocaleTimeString("zh-CN")}`
              : ""}
          </p>
        </>
      ) : null}

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
