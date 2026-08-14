import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, createTask, fetchTask } from "./tasks.ts";


const task = {
  task_id: "0ae8f805-9e62-4e73-b072-49d648bb0f87",
  repository_url: "https://github.com/example/project.git",
  issue: "Fix the parser",
  status: "created" as const,
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
