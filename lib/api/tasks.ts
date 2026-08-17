export type TaskStatus =
  | "created"
  | "queued"
  | "cloning"
  | "cloned"
  | "indexing"
  | "indexed"
  | "retrieving"
  | "retrieved"
  | "analyzing"
  | "waiting_approval"
  | "decision_pending"
  | "revising"
  | "approved"
  | "rejected"
  | "recovery_blocked"
  | "failed";

export type TaskFailure = {
  code: string;
  message: string;
};

export type Task = {
  task_id: string;
  repository_url: string;
  issue: string;
  status: TaskStatus;
  failure: TaskFailure | null;
  created_at: string;
  updated_at: string;
};

export type RepositoryTreeEntry = {
  path: string;
  kind: "file" | "symlink" | "submodule";
  size_bytes: number | null;
};

export type RepositoryTree = {
  task_id: string;
  canonical_url: string;
  commit_sha: string;
  file_count: number;
  total_bytes: number;
  truncated: boolean;
  cloned_at: string;
  entries: RepositoryTreeEntry[];
};

export type CodeSymbol = {
  local_id: number;
  parent_local_id: number | null;
  kind: "class" | "function" | "method";
  name: string;
  qualified_name: string;
  start_line: number;
  end_line: number;
  signature: string | null;
  decorators: string[];
  is_async: boolean;
  is_test: boolean;
  is_fixture: boolean;
};

export type CodeImport = {
  kind: "import" | "from";
  module: string | null;
  imported_name: string | null;
  alias: string | null;
  relative_level: number;
  scope: string | null;
  line: number;
};

export type CodeStructureFile = {
  path: string;
  module_name: string | null;
  is_test_file: boolean;
  parse_status: "parsed" | "syntax_error" | "read_error";
  parse_error: string | null;
  symbols: CodeSymbol[];
  imports: CodeImport[];
};

export type CodeStructure = {
  task_id: string;
  commit_sha: string;
  parser_version: string;
  python_version: string;
  indexed_at: string;
  counts: {
    files: number;
    parsed_files: number;
    symbols: number;
    imports: number;
    tests: number;
    parse_errors: number;
  };
  truncated: boolean;
  files: CodeStructureFile[];
};

export type RetrievalResult = {
  rank: number;
  path: string;
  symbol: string | null;
  kind: string;
  start_line: number;
  end_line: number;
  snippet: string;
  matched_channels: string[];
  channel_ranks: Record<string, number>;
  channel_scores: Record<string, number>;
  rrf_score: number;
  rerank_score: number;
};

export type Retrieval = {
  task_id: string;
  commit_sha: string;
  query: string;
  embedding: {
    provider: string;
    model: string;
    dimensions: number;
  };
  versions: {
    chunker: string;
    fusion: string;
    reranker: string;
  };
  created_at: string;
  counts: {
    chunks: number;
    keyword_candidates: number;
    symbol_candidates: number;
    vector_candidates: number;
    results: number;
  };
  results: RetrievalResult[];
};

export type EvidenceReference = {
  description: string;
  evidence_ranks: number[];
};

export type Planning = {
  task_id: string;
  commit_sha: string;
  run: {
    id: string;
    graph_version: string;
    provider: string;
    model: string;
    analysis_prompt_version: string;
    plan_prompt_version: string;
    evidence_count: number;
    evidence_sha256: string;
    evidence_truncated: boolean;
    created_at: string;
  };
  analysis: {
    summary: string;
    acceptance_criteria: Array<EvidenceReference & { id: string }>;
    constraints: EvidenceReference[];
    assumptions: EvidenceReference[];
    affected_areas: Array<{
      path: string;
      symbol: string | null;
      reason: string;
      evidence_ranks: number[];
    }>;
    risks: Array<{
      description: string;
      mitigation: string;
      evidence_ranks: number[];
    }>;
  };
  plan: {
    version: number;
    status: "proposed" | "approved" | "rejected" | "superseded";
    plan_id: string | null;
    supersedes_plan_id: string | null;
    revision_feedback: string | null;
    steps: Array<{
      order: number;
      title: string;
      description: string;
      paths: string[];
      symbols: string[];
      evidence_ranks: number[];
    }>;
    test_strategy: Array<{
      description: string;
      target_paths: string[];
      evidence_ranks: number[];
    }>;
    risk_notes: string[];
    created_at: string;
    decided_at: string | null;
  };
  decisions: PlanningDecisionHistory[];
};

export type PlanningDecisionAction = "approve" | "request_changes" | "reject";

export type PlanningDecisionHistory = {
  decision_id: string;
  action: PlanningDecisionAction;
  status: "pending" | "applied" | "failed";
  plan_version: number;
  comment: string | null;
  failure_code: string | null;
  failure_message: string | null;
  created_at: string;
  applied_at: string | null;
};

export type PlanningDecisionInput = {
  action: PlanningDecisionAction;
  expected_plan_version: number;
  idempotency_key: string;
  comment: string | null;
};

export type PlanningDecision = {
  decision_id: string;
  task_id: string;
  action: PlanningDecisionAction;
  status: "pending" | "applied" | "failed";
  plan_version: number;
  task_status: TaskStatus;
  comment: string | null;
  created_at: string;
  applied_at: string | null;
};

export type CreateTaskInput = {
  repository_url: string;
  issue: string;
};

export type ApiErrorDetail = {
  field: string;
  message: string;
};

type ErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
    details?: ApiErrorDetail[];
  };
};

const DEFAULT_API_BASE_URL = "http://localhost:8000";

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(
    /\/$/,
    "",
  );
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T | ErrorEnvelope;
  if (response.ok) {
    return body as T;
  }

  const error = (body as ErrorEnvelope).error;
  throw new ApiError(
    response.status,
    error?.code ?? "REQUEST_FAILED",
    error?.message ?? "请求失败，请稍后重试",
    error?.details ?? [],
  );
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  const response = await fetch(`${apiBaseUrl()}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseResponse<Task>(response);
}

export async function fetchTask(
  taskId: string,
  signal?: AbortSignal,
): Promise<Task> {
  const response = await fetch(`${apiBaseUrl()}/api/v1/tasks/${taskId}`, {
    method: "GET",
    cache: "no-store",
    signal,
  });
  return parseResponse<Task>(response);
}

export async function fetchRepositoryTree(
  taskId: string,
  signal?: AbortSignal,
): Promise<RepositoryTree> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/tasks/${taskId}/repository/tree`,
    { method: "GET", cache: "no-store", signal },
  );
  return parseResponse<RepositoryTree>(response);
}

export async function fetchCodeStructure(
  taskId: string,
  signal?: AbortSignal,
): Promise<CodeStructure> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/tasks/${taskId}/code/structure`,
    { method: "GET", cache: "no-store", signal },
  );
  return parseResponse<CodeStructure>(response);
}

export async function fetchRetrieval(
  taskId: string,
  signal?: AbortSignal,
): Promise<Retrieval> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/tasks/${taskId}/retrieval`,
    { method: "GET", cache: "no-store", signal },
  );
  return parseResponse<Retrieval>(response);
}

export async function fetchPlanning(
  taskId: string,
  signal?: AbortSignal,
): Promise<Planning> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/tasks/${taskId}/planning`,
    { method: "GET", cache: "no-store", signal },
  );
  return parseResponse<Planning>(response);
}

export async function submitPlanningDecision(
  taskId: string,
  input: PlanningDecisionInput,
): Promise<PlanningDecision> {
  const response = await fetch(
    `${apiBaseUrl()}/api/v1/tasks/${taskId}/planning/decisions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return parseResponse<PlanningDecision>(response);
}
