"use client";

import { useRef, useState } from "react";

import {
  ApiError,
  createImplementation,
  createImplementationTest,
} from "@/lib/api/tasks";
import type { Implementation, TaskStatus } from "@/lib/api/tasks";


type Props = {
  taskId: string;
  taskStatus: TaskStatus;
  planVersion: number;
  implementation?: Implementation;
  onSubmitted: () => void;
};

type Patch = NonNullable<Implementation["patch"]>;
type TestEvidence = NonNullable<Implementation["test"]>;

function useImplementationActions(props: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const patchKey = useRef<string | null>(null);
  const testKey = useRef<string | null>(null);

  async function submit(action: () => Promise<Implementation>) {
    setSubmitting(true);
    setError("");
    try {
      await action();
      props.onSubmitted();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "实现请求失败，请重试。");
      if (cause instanceof ApiError && cause.status === 409) props.onSubmitted();
    } finally {
      setSubmitting(false);
    }
  }

  function generatePatch() {
    patchKey.current ??= crypto.randomUUID();
    return submit(() =>
      createImplementation(props.taskId, props.planVersion, patchKey.current!),
    );
  }

  function runTests() {
    if (!props.implementation?.patch) return Promise.resolve();
    testKey.current ??= crypto.randomUUID();
    return submit(() => createImplementationTest(
      props.taskId, props.implementation!.patch!.sha256, testKey.current!,
    ));
  }
  return { submitting, error, generatePatch, runTests };
}

function PatchEvidence({ patch, commit }: { patch: Patch; commit: string }) {
  return <>
    <dl className="implementation-meta">
      <div><dt>Patch SHA</dt><dd className="mono">{patch.sha256}</dd></div>
      <div><dt>文件</dt><dd>{patch.file_count}</dd></div>
      <div><dt>变更</dt><dd>+{patch.insertions} / -{patch.deletions}</dd></div>
      <div><dt>基础 Commit</dt><dd className="mono">{commit}</dd></div>
    </dl>
    <pre className="patch-diff" tabIndex={0}>{patch.unified_diff}</pre>
  </>;
}

function TestResult({ test }: { test: TestEvidence }) {
  return <section className="test-evidence">
    <h3>pytest 执行证据</h3>
    <p className="mono">{test.command_argv.join(" ")}</p>
    <dl className="implementation-meta">
      <div><dt>状态</dt><dd>{test.status}</dd></div>
      <div><dt>退出码</dt><dd>{test.exit_code ?? "—"}</dd></div>
      <div><dt>耗时</dt><dd>{test.duration_ms ?? "—"} ms</dd></div>
      <div><dt>超时</dt><dd>{test.timed_out ? "是" : "否"}</dd></div>
      <div><dt>Runner 镜像</dt><dd className="mono">{test.runner_image}</dd></div>
      <div><dt>输出 SHA256</dt><dd className="mono">{test.output_sha256 ?? "—"}</dd></div>
    </dl>
    {test.stdout ? <pre>{test.stdout}</pre> : null}
    {test.stderr ? <pre className="test-stderr">{test.stderr}</pre> : null}
    {test.output_truncated ? <small>输出已按安全上限截断；完整流 Hash 已保存。</small> : null}
  </section>;
}

export default function ImplementationResults(props: Props) {
  const { taskStatus, implementation } = props;
  const actions = useImplementationActions(props);
  return <section className="implementation" aria-labelledby="implementation-title">
    <div className="planning-heading">
      <div><p className="card-label">ISOLATED IMPLEMENTATION</p>
        <h2 id="implementation-title">本地 Patch 与测试证据</h2></div>
      <span>{implementation?.run.status ?? "not_started"}</span>
    </div>
    {taskStatus === "approved" && !implementation ? <div className="implementation-action">
      <p>只会从固定 Commit 创建隔离 Worktree；不会修改来源仓库、Commit 或 Push。</p>
      <button disabled={actions.submitting} onClick={() => void actions.generatePatch()}>生成本地 Patch</button>
    </div> : null}
    {implementation?.patch ? <PatchEvidence patch={implementation.patch} commit={implementation.run.base_commit} />
      : implementation ? <p className="implementation-progress">本机模型正在生成受限文件替换并由 Git 计算 Diff。</p> : null}
    {taskStatus === "patch_ready" && implementation?.patch && !implementation.test ?
      <div className="implementation-action warning">
        <p>pytest 会执行仓库代码。确认上方 Diff 后，测试只在无网络受限容器中运行。</p>
        <button disabled={actions.submitting} onClick={() => void actions.runTests()}>运行白名单 pytest</button>
      </div> : null}
    {implementation?.test ? <TestResult test={implementation.test} /> : null}
    {actions.error ? <p className="form-error" role="alert">{actions.error}</p> : null}
  </section>;
}
