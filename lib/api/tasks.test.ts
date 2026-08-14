import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  createTask,
  fetchCodeStructure,
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


test("fetchCodeStructure requests the dedicated M3 endpoint", async () => {
  let capturedRequest: Request | undefined;
  const structure = {
    task_id: task.task_id,
    commit_sha: "a".repeat(40),
    parser_version: "py-ast-v1",
    python_version: "3.9.6",
    indexed_at: "2026-08-14T11:00:00Z",
    counts: {
      files: 1,
      parsed_files: 1,
      symbols: 1,
      imports: 1,
      tests: 0,
      parse_errors: 0,
    },
    truncated: false,
    files: [
      {
        path: "service.py",
        module_name: "service",
        is_test_file: false,
        parse_status: "parsed",
        parse_error: null,
        symbols: [
          {
            local_id: 1,
            parent_local_id: null,
            kind: "class",
            name: "Service",
            qualified_name: "Service",
            start_line: 1,
            end_line: 2,
            signature: null,
            decorators: [],
            is_async: false,
            is_test: false,
            is_fixture: false,
          },
        ],
        imports: [
          {
            kind: "import",
            module: "os",
            imported_name: null,
            alias: null,
            relative_level: 0,
            scope: null,
            line: 1,
          },
        ],
      },
    ],
  };
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(structure);
  };

  const result = await fetchCodeStructure(task.task_id);

  assert.deepEqual(result, structure);
  assert.equal(
    new URL(capturedRequest?.url ?? "").pathname,
    `/api/v1/tasks/${task.task_id}/code/structure`,
  );
  assert.equal(capturedRequest?.cache, "no-store");
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
