"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  CodeStructure,
  fetchCodeStructure,
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
  codeStructure?: CodeStructure;
  error: string;
  lastSyncedAt?: Date;
};

async function loadTaskSnapshot(taskId: string, signal: AbortSignal) {
  const task = await fetchTask(taskId, signal);
  let repositoryTree: RepositoryTree | undefined;
  let codeStructure: CodeStructure | undefined;
  if (task.status === "indexed") {
    [repositoryTree, codeStructure] = await Promise.all([
      fetchRepositoryTree(taskId, signal),
      fetchCodeStructure(taskId, signal),
    ]);
  } else if (task.status === "cloned") {
    repositoryTree = await fetchRepositoryTree(taskId, signal);
  } else if (task.status === "failed") {
    repositoryTree = await fetchTreeAfterFailure(taskId, signal);
  }
  return {
    task,
    repositoryTree,
    codeStructure,
    shouldContinue: shouldContinueTaskPolling(task.status),
  };
}

async function fetchTreeAfterFailure(
  taskId: string,
  signal: AbortSignal,
): Promise<RepositoryTree | undefined> {
  try {
    return await fetchRepositoryTree(taskId, signal);
  } catch (error) {
    if (error instanceof ApiError && error.code === "REPOSITORY_NOT_READY") {
      return undefined;
    }
    throw error;
  }
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
