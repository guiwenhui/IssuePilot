export type TaskStatus = "created";

export type Task = {
  task_id: string;
  repository_url: string;
  issue: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
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

async function parseResponse(response: Response): Promise<Task> {
  const body = (await response.json()) as Task | ErrorEnvelope;
  if (response.ok) {
    return body as Task;
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
  return parseResponse(response);
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
  return parseResponse(response);
}
