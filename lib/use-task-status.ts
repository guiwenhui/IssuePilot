"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  fetchRepositoryTree,
  fetchTask,
  RepositoryTree,
  Task,
} from "@/lib/api/tasks";
import {
  PollHandle,
  schedulePoll,
  shouldContinueTaskPolling,
  shouldRetryPoll,
} from "@/lib/polling";


type TaskStatusState = {
  task?: Task;
  repositoryTree?: RepositoryTree;
  error: string;
  lastSyncedAt?: Date;
};

async function loadTaskSnapshot(taskId: string, signal: AbortSignal) {
  const task = await fetchTask(taskId, signal);
  const repositoryTree =
    task.status === "cloned"
      ? await fetchRepositoryTree(taskId, signal)
      : undefined;
  return {
    task,
    repositoryTree,
    shouldContinue: shouldContinueTaskPolling(task.status),
  };
}

function retryForError(error: unknown): boolean {
  return error instanceof ApiError ? shouldRetryPoll(error.status) : true;
}

function messageForError(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "连接失败，IssuePilot 将继续重试。";
}

export function useTaskStatus(taskId: string): TaskStatusState {
  const [state, setState] = useState<TaskStatusState>({ error: "" });
  const timer = useRef<PollHandle | undefined>(undefined);

  useEffect(() => {
    let active = true;
    let controller: AbortController | undefined;

    async function load() {
      let shouldContinue = true;
      controller = new AbortController();
      try {
        const snapshot = await loadTaskSnapshot(taskId, controller.signal);
        shouldContinue = snapshot.shouldContinue;
        if (active) {
          setState({ ...snapshot, error: "", lastSyncedAt: new Date() });
        }
      } catch (error) {
        shouldContinue = retryForError(error);
        if (active && !(error instanceof DOMException)) {
          setState((current) => ({ ...current, error: messageForError(error) }));
        }
      } finally {
        if (active && shouldContinue) {
          timer.current = schedulePoll(() => void load());
        }
      }
    }

    void load();
    return () => {
      active = false;
      controller?.abort();
      if (timer.current !== undefined) clearTimeout(timer.current);
    };
  }, [taskId]);

  return state;
}
