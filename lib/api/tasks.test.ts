import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  createTask,
  fetchRepositoryTree,
  fetchTask,
} from "./tasks.ts";


const task = {
  task_id: "0ae8f805-9e62-4e73-b072-49d648bb0f87",
  repository_url: "https://github.com/example/project.git",
  issue: "Fix the parser",
  status: "created" as const,
  failure: null,
  created_at: "2026-08-13T10:00:00Z",
  updated_at: "2026-08-13T10:00:00Z",
};


test("createTask posts the API contract", async () => {
  let capturedRequest: Request | undefined;
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(task, { status: 201 });
  };

  const result = await createTask({
    repository_url: task.repository_url,
    issue: task.issue,
  });

  assert.deepEqual(result, task);
  assert.equal(capturedRequest?.method, "POST");
  assert.deepEqual(await capturedRequest?.json(), {
    repository_url: task.repository_url,
    issue: task.issue,
  });
});


test("fetchTask requests fresh state", async () => {
  let capturedRequest: Request | undefined;
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(task);
  };

  await fetchTask(task.task_id);

  assert.equal(capturedRequest?.method, "GET");
  assert.equal(capturedRequest?.cache, "no-store");
});


test("API errors preserve structured field details", async () => {
  globalThis.fetch = async () =>
    Response.json(
      {
        error: {
          code: "VALIDATION_ERROR",
          message: "请求参数不合法",
          details: [
            { field: "repository_url", message: "必须使用 HTTPS" },
          ],
        },
      },
      { status: 422 },
    );

  await assert.rejects(
    createTask({ repository_url: "http://example.com", issue: "Fix" }),
    (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, "VALIDATION_ERROR");
      assert.equal(error.details[0]?.field, "repository_url");
      return true;
    },
  );
});


test("fetchRepositoryTree requests the dedicated fresh endpoint", async () => {
  let capturedRequest: Request | undefined;
  const tree = {
    task_id: task.task_id,
    canonical_url: task.repository_url,
    commit_sha: "a".repeat(40),
    file_count: 1,
    total_bytes: 12,
    truncated: false,
    cloned_at: "2026-08-14T10:00:00Z",
    entries: [{ path: "README.md", kind: "file" as const, size_bytes: 12 }],
  };
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(tree);
  };

  const result = await fetchRepositoryTree(task.task_id);

  assert.deepEqual(result, tree);
  assert.equal(
    new URL(capturedRequest?.url ?? "").pathname,
    `/api/v1/tasks/${task.task_id}/repository/tree`,
  );
  assert.equal(capturedRequest?.cache, "no-store");
});
