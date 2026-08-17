"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, createTask } from "@/lib/api/tasks";


type FieldErrors = Partial<Record<"repository_url" | "issue", string>>;

function extractFieldErrors(error: ApiError): FieldErrors {
  return error.details.reduce<FieldErrors>((errors, detail) => {
    if (detail.field === "repository_url" || detail.field === "issue") {
      errors[detail.field] = detail.message;
    }
    return errors;
  }, {});
}

export default function TaskCreateForm() {
  const router = useRouter();
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [issue, setIssue] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setFieldErrors({});
    setFormError("");

    try {
      const task = await createTask({
        repository_url: repositoryUrl,
        issue,
      });
      router.push(`/tasks/${task.task_id}`);
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(extractFieldErrors(error));
        setFormError(error.message);
      } else {
        setFormError("无法连接 IssuePilot API，请确认后端服务正在运行。");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="task-form" onSubmit={handleSubmit} noValidate>
      <div className="field-group">
        <label htmlFor="repository-url">公开仓库 HTTPS 地址</label>
        <input
          id="repository-url"
          name="repository_url"
          type="url"
          inputMode="url"
          autoComplete="url"
          placeholder="https://github.com/example/project.git"
          value={repositoryUrl}
          onChange={(event) => setRepositoryUrl(event.target.value)}
          aria-invalid={Boolean(fieldErrors.repository_url)}
          aria-describedby="repository-help repository-error"
          required
          disabled={isSubmitting}
        />
        <small id="repository-help">M5 仅处理公开 github.com 仓库中的 tracked Python 文件，并在本机完成检索与规划。</small>
        {fieldErrors.repository_url ? (
          <p className="field-error" id="repository-error">
            {fieldErrors.repository_url}
          </p>
        ) : null}
      </div>

      <div className="field-group">
        <label htmlFor="issue">Issue 描述</label>
        <textarea
          id="issue"
          name="issue"
          rows={7}
          maxLength={20_000}
          placeholder="描述期望行为、当前问题和验收条件。"
          value={issue}
          onChange={(event) => setIssue(event.target.value)}
          aria-invalid={Boolean(fieldErrors.issue)}
          aria-describedby="issue-error"
          required
          disabled={isSubmitting}
        />
        {fieldErrors.issue ? (
          <p className="field-error" id="issue-error">
            {fieldErrors.issue}
          </p>
        ) : null}
      </div>

      {formError ? (
        <p className="form-error" role="alert">
          {formError}
        </p>
      ) : null}

      <button className="primary-button" type="submit" disabled={isSubmitting}>
        {isSubmitting ? "正在创建任务…" : "创建并生成实施计划"}
      </button>
    </form>
  );
}
