"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  CodeStructure,
  fetchCodeStructure,
  fetchImplementation,
  fetchPlanning,
  fetchRepositoryTree,
  fetchRetrieval,
  fetchTask,
  RepositoryTree,
  Implementation,
  Planning,
  Retrieval,
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
  retrieval?: Retrieval;
  planning?: Planning;
  implementation?: Implementation;
  error: string;
  lastSyncedAt?: Date;
  refresh: () => void;
};

const PLANNING_STATUSES = [
  "waiting_approval", "decision_pending", "revising", "approved", "rejected",
  "recovery_blocked", "implementation_pending", "generating_patch",
  "patch_ready", "test_pending", "testing", "tested", "test_failed",
];

const PRE_IMPLEMENTATION_STATUSES = [
  "waiting_approval", "decision_pending", "revising", "approved", "rejected",
];

async function loadTaskSnapshot(taskId: string, signal: AbortSignal) {
  const task = await fetchTask(taskId, signal);
  let repositoryTree: RepositoryTree | undefined;
  let codeStructure: CodeStructure | undefined;
  let retrieval: Retrieval | undefined;
  let planning: Planning | undefined;
  let implementation: Implementation | undefined;
  if (PLANNING_STATUSES.includes(task.status)) {
    ({ repositoryTree, codeStructure, retrieval, planning, implementation } =
      await loadPlanningSnapshot(taskId, task.status, signal));
  } else if (task.status === "retrieved") {
    [repositoryTree, codeStructure, retrieval] = await Promise.all([
      fetchRepositoryTree(taskId, signal),
      fetchCodeStructure(taskId, signal),
      fetchRetrieval(taskId, signal),
    ]);
  } else if (task.status === "indexed") {
    [repositoryTree, codeStructure] = await Promise.all([
      fetchRepositoryTree(taskId, signal),
      fetchCodeStructure(taskId, signal),
    ]);
  } else if (task.status === "cloned") {
    repositoryTree = await fetchRepositoryTree(taskId, signal);
  } else if (task.status === "failed") {
    [repositoryTree, codeStructure, retrieval, planning] = await Promise.all([
      fetchTreeAfterFailure(taskId, signal),
      fetchCodeStructureAfterFailure(taskId, signal),
      fetchRetrievalAfterFailure(taskId, signal),
      fetchPlanningAfterFailure(taskId, signal),
    ]);
    implementation = await fetchImplementationAfterFailure(taskId, signal);
  }
  return {
    task,
    repositoryTree,
    codeStructure,
    retrieval,
    planning,
    implementation,
    shouldContinue: shouldContinueTaskPolling(task.status),
  };
}

async function loadPlanningSnapshot(
  taskId: string,
  status: string,
  signal: AbortSignal,
) {
  const [repositoryTree, codeStructure, retrieval, planning] = await Promise.all([
    fetchRepositoryTree(taskId, signal),
    fetchCodeStructure(taskId, signal),
    fetchRetrieval(taskId, signal),
    fetchPlanning(taskId, signal),
  ]);
  let implementation: Implementation | undefined;
  if (status === "recovery_blocked") {
    implementation = await fetchImplementationAfterFailure(taskId, signal);
  } else if (!PRE_IMPLEMENTATION_STATUSES.includes(status)) {
    implementation = await fetchImplementation(taskId, signal);
  }
  return { repositoryTree, codeStructure, retrieval, planning, implementation };
}

async function fetchImplementationAfterFailure(
  taskId: string,
  signal: AbortSignal,
): Promise<Implementation | undefined> {
  try {
    return await fetchImplementation(taskId, signal);
  } catch (error) {
    if (error instanceof ApiError && error.code === "IMPLEMENTATION_NOT_READY") {
      return undefined;
    }
    throw error;
  }
}

async function fetchRetrievalAfterFailure(
  taskId: string,
  signal: AbortSignal,
): Promise<Retrieval | undefined> {
  try {
    return await fetchRetrieval(taskId, signal);
  } catch (error) {
    if (error instanceof ApiError && error.code === "RETRIEVAL_NOT_READY") {
      return undefined;
    }
    throw error;
  }
}

async function fetchPlanningAfterFailure(
  taskId: string,
  signal: AbortSignal,
): Promise<Planning | undefined> {
  try {
    return await fetchPlanning(taskId, signal);
  } catch (error) {
    if (error instanceof ApiError && error.code === "PLANNING_NOT_READY") {
      return undefined;
    }
    throw error;
  }
}

async function fetchCodeStructureAfterFailure(
  taskId: string,
  signal: AbortSignal,
): Promise<CodeStructure | undefined> {
  try {
    return await fetchCodeStructure(taskId, signal);
  } catch (error) {
    if (error instanceof ApiError && error.code === "CODE_INDEX_NOT_READY") {
      return undefined;
    }
    throw error;
  }
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
  const [refreshVersion, setRefreshVersion] = useState(0);
  const refresh = () => setRefreshVersion((value) => value + 1);
  const [state, setState] = useState<Omit<TaskStatusState, "refresh">>({
    error: "",
  });
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
  }, [taskId, refreshVersion]);

  return { ...state, refresh };
}
