import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  createTask,
  fetchCodeStructure,
  fetchPlanning,
  fetchRetrieval,
  fetchRepositoryTree,
  fetchTask,
  submitPlanningDecision,
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


test("fetchRetrieval requests the dedicated M4 endpoint", async () => {
  let capturedRequest: Request | undefined;
  const retrieval = {
    task_id: task.task_id,
    commit_sha: "a".repeat(40),
    query: "Fix escape html output",
    embedding: {
      provider: "ollama",
      model: "qwen3-embedding:0.6b",
      dimensions: 1024,
    },
    versions: {
      chunker: "python-symbol-v1",
      fusion: "rrf-v1",
      reranker: "rules-v1",
    },
    created_at: "2026-08-16T10:00:00Z",
    counts: {
      chunks: 12,
      keyword_candidates: 8,
      symbol_candidates: 3,
      vector_candidates: 12,
      results: 1,
    },
    results: [
      {
        rank: 1,
        path: "src/escape.py",
        symbol: "escape",
        kind: "function",
        start_line: 1,
        end_line: 4,
        snippet: "def escape(value): ...",
        matched_channels: ["keyword", "symbol", "vector"],
        channel_ranks: { keyword: 1, symbol: 1, vector: 2 },
        channel_scores: { keyword: 0.7, symbol: 3, vector: 0.9 },
        rrf_score: 0.04,
        rerank_score: 0.07,
      },
    ],
  };
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(retrieval);
  };

  const result = await fetchRetrieval(task.task_id);

  assert.deepEqual(result, retrieval);
  assert.equal(
    new URL(capturedRequest?.url ?? "").pathname,
    `/api/v1/tasks/${task.task_id}/retrieval`,
  );
  assert.equal(capturedRequest?.cache, "no-store");
});


test("fetchPlanning requests the dedicated M5 endpoint", async () => {
  let capturedRequest: Request | undefined;
  const planning = {
    task_id: task.task_id,
    commit_sha: "a".repeat(40),
    run: {
      id: "b".repeat(36),
      graph_version: "planning-graph-v1",
      provider: "ollama",
      model: "qwen3:8b",
      analysis_prompt_version: "analysis-v1",
      plan_prompt_version: "plan-v1",
      evidence_count: 2,
      evidence_sha256: "c".repeat(64),
      evidence_truncated: false,
      created_at: "2026-08-17T10:00:00Z",
    },
    analysis: {
      summary: "Handle nullable escaping.",
      acceptance_criteria: [],
      constraints: [],
      assumptions: [],
      affected_areas: [],
      risks: [],
    },
    plan: {
      version: 1,
      status: "proposed",
      plan_id: "11111111-1111-4111-8111-111111111111",
      supersedes_plan_id: null,
      revision_feedback: null,
      steps: [],
      test_strategy: [],
      risk_notes: [],
      created_at: "2026-08-17T10:00:00Z",
      decided_at: null,
    },
    decisions: [],
  };
  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init);
    return Response.json(planning);
  };

  const result = await fetchPlanning(task.task_id);

  assert.deepEqual(result, planning);
  assert.equal(
    new URL(capturedRequest?.url ?? "").pathname,
    `/api/v1/tasks/${task.task_id}/planning`,
  );
  assert.equal(capturedRequest?.cache, "no-store");
});

test("submitPlanningDecision posts the M6 versioned idempotent contract", async () => {
  let request: Request | undefined;
  globalThis.fetch = async (input, init) => {
    request = new Request(input, init);
    return Response.json({
      decision_id: "22222222-2222-4222-8222-222222222222",
      task_id: task.task_id,
      action: "approve",
      status: "pending",
      plan_version: 1,
      task_status: "decision_pending",
      comment: null,
      created_at: "2026-08-17T00:00:00Z",
      applied_at: null,
    }, { status: 202 });
  };

  await submitPlanningDecision(task.task_id, {
    action: "approve",
    expected_plan_version: 1,
    idempotency_key: "11111111-1111-4111-8111-111111111111",
    comment: null,
  });

  assert.equal(request?.method, "POST");
  assert.deepEqual(await request?.json(), {
    action: "approve",
    expected_plan_version: 1,
    idempotency_key: "11111111-1111-4111-8111-111111111111",
    comment: null,
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
